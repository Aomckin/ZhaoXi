"""QQ/NapCat I/O plugin. No cognitive state or provider access."""
import asyncio
import logging
from dataclasses import dataclass, field
from time import monotonic
from urllib.parse import urlparse
from zhaoxi.config.external_timing import load_external_timing
from zhaoxi.perception.images import ImageResolver
from zhaoxi.sdk.external_source import SourceCapabilities, SendResult
from zhaoxi_ext.qq_napcat.codec import decode
from zhaoxi_ext.qq_napcat.outbound import send_reply
from zhaoxi_ext.qq_napcat.transport import QQTransport
from zhaoxi_ext.qq_napcat.config import QQConfig

logger = logging.getLogger("QQ_PLUGIN")

@dataclass
class _PendingDirect:
    items: list
    started_at: float
    last_at: float
    changed: asyncio.Event = field(default_factory=asyncio.Event)

class QQNapCatPlugin:
    plugin_id = "qq_napcat"

    def __init__(self, config: QQConfig | None = None):
        self.config = config or QQConfig.load()
        self.transport = QQTransport(self.config.ws_url, self.config.access_token,
            self.config.reconnect_seconds, on_state=self._on_state,
            expected_user_id=self.config.bot_user_id)
        parsed = urlparse(self.config.ws_url)
        self.images = ImageResolver(".zhaoxi/tmp/plugins", 10_485_760, 24,
                                    trusted_host=parsed.hostname, trusted_port=parsed.port)
        self.sink = None
        self._pending_direct = {}
        self._pending_lock = asyncio.Lock()
        self.received_count = 0
        self.sent_count = 0

    def _on_state(self, state):
        logger.info("QQ transport state=%s", state)

    @staticmethod
    def _merge_direct(items):
        if len(items) == 1:
            return items[0]
        first, last = items[0], items[-1]
        refs = [item.raw_ref for item in items if item.raw_ref]
        return first.model_copy(update={
            "content": "\n".join(item.content for item in items if item.content),
            "parts": [part for item in items for part in item.effective_parts],
            "attachments": [attachment for item in items for attachment in item.attachments],
            "raw_ref": last.raw_ref,
            "received_at": last.received_at,
            "metadata": {**last.metadata, "merged_refs": refs,
                         "raw_observations":[item.model_dump(mode="json") for item in items]},
        })

    async def _debounce_direct(self, item):
        seconds = load_external_timing(self.config.interface_settings_path).debounce_seconds
        if not seconds or (item.conversation_kind != "private" and not item.directed_to_zhaoxi):
            return item
        key = (item.conversation_kind or "", item.conversation_id or "", item.actor_id or "")
        now = monotonic()
        async with self._pending_lock:
            pending = self._pending_direct.get(key)
            if pending is not None:
                pending.items.append(item)
                pending.last_at = now
                pending.changed.set()
                return None
            pending = _PendingDirect([item], now, now)
            self._pending_direct[key] = pending
        try:
            while True:
                async with self._pending_lock:
                    pending.changed.clear()
                    remaining = min(pending.last_at + seconds, pending.started_at + 30) - monotonic()
                    if len(pending.items) >= 8 or remaining <= 0:
                        self._pending_direct.pop(key, None)
                        return self._merge_direct(pending.items)
                try:
                    await asyncio.wait_for(pending.changed.wait(), timeout=remaining)
                except TimeoutError:
                    pass
        finally:
            async with self._pending_lock:
                if self._pending_direct.get(key) is pending:
                    self._pending_direct.pop(key, None)

    async def on_event(self, event):
        if event.get("post_type") != "message" or not self.transport.identity_verified:
            return
        if self.config.bot_user_id and self.transport.self_id != self.config.bot_user_id:
            return
        if event.get("self_id") and str(event["self_id"]) != str(self.transport.self_id):
            return
        item = decode(event, self_id=self.transport.self_id, owner_id=self.config.owner_user_id)
        if item is None:
            return
        if item.actor_id in {value.strip() for value in self.config.external_bot_user_ids.split(",") if value.strip()}:
            item.metadata["sender_is_bot"] = True
        reply_id = item.metadata.get("reply_to")
        if reply_id and not item.directed_to_zhaoxi:
            try:
                original = await self.transport.action("get_msg", {"message_id": int(reply_id)})
                original_data = original.get("data") or {}
                if str(original_data.get("user_id") or (original_data.get("sender") or {}).get("user_id")) == str(self.transport.self_id):
                    item.directed_to_zhaoxi = True
            except Exception as exc:
                logger.warning("reply lookup failed type=%s", type(exc).__name__)
        item = await self._debounce_direct(item)
        if item is None:
            return
        cached_images = {}
        for part in item.parts:
            if part.type == "image":
                resolved = await self.images.resolve({"url": part.url, "file": part.file})
                if resolved:
                    cached_images[part.url or part.file] = resolved
                    part.url, part.file = resolved, None
        for original in item.metadata.get("raw_observations", []):
            for part in original.get("parts", []):
                if part.get("type") == "image" and (part.get("url") or part.get("file")) in cached_images:
                    part["url"], part["file"] = cached_images[part.get("url") or part.get("file")], None
        self.received_count += 1
        await self.sink.emit(item)

    async def start(self, sink):
        self.sink = sink
        await self.transport.run(self.on_event)

    async def stop(self):
        await self.transport.close()
        self.sink = None

    def capabilities(self):
        return SourceCapabilities(text_in=True, text_out=True, image_in=True, image_out=True,
                                  reply=True, mention=True, private_chat=True, group_chat=True,
                                  realtime=True)

    async def send(self, target, content):
        if not self.transport.identity_verified:
            return SendResult(sent=False, error="source disconnected")
        try:
            count = await send_reply(self.transport, target, content, settings=self.config)
            self.sent_count += count
            return SendResult(sent=True, segment_count=count)
        except Exception as exc:
            logger.warning("QQ send failed type=%s", type(exc).__name__)
            return SendResult(sent=False, error=type(exc).__name__)

    async def reply(self, target, reply_to, content):
        return await self.send(target.model_copy(update={"message_ref": reply_to}), content)

    def diagnostics(self):
        return {"connected": self.transport.connected,
                "identity_verified": self.transport.identity_verified,
                "expected_qq": self.config.bot_user_id or None,
                "logged_in_qq": self.transport.self_id,
                "reconnect_count": self.transport.reconnect_count,
                "last_error": self.transport.last_error,
                "received_count": self.received_count, "sent_count": self.sent_count}
