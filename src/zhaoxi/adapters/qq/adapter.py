"""NapCat source adapter; failures are isolated from the core lifecycle."""
import asyncio
import logging
from dataclasses import dataclass, field
from time import monotonic

from zhaoxi.config.external_timing import load_external_timing
from zhaoxi.perception.models import AttentionHint
from zhaoxi.perception.router import route
from zhaoxi.adapters.qq.codec import decode
from zhaoxi.adapters.qq.outbound import send_reply
from zhaoxi.adapters.qq.transport import QQTransport

logger = logging.getLogger("QQ_ADAPTER")


@dataclass
class _PendingDirect:
    items: list
    started_at: float
    last_at: float
    changed: asyncio.Event = field(default_factory=asyncio.Event)


class QQAdapter:
    def __init__(self, runtime, settings):
        self.runtime = runtime
        self.settings = settings
        self.transport = QQTransport(settings.qq_ws_url, settings.qq_access_token,
                                     settings.qq_reconnect_seconds,
                                     on_state=self._on_state,
                                     expected_user_id=settings.qq_bot_user_id)
        self._pending_direct: dict[tuple[str, str, str], _PendingDirect] = {}
        self._pending_lock = asyncio.Lock()
        self.received_count = 0
        self.sent_count = 0
        self.runtime.source = self

    def _on_state(self, state):
        self.runtime.agent.metrics.increment("qq." + state)
        self.runtime.publish_runtime_state()
        if state in {"connected", "disconnected"} and self.settings.interaction_ledger_enabled:
            self.runtime.ledger.record("channel_" + state, "qq",
                "QQ 通道已连接" if state == "connected" else "QQ 通道已断开")

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
            "metadata": {**last.metadata, "merged_refs": refs},
        })

    async def _debounce_direct(self, item):
        seconds = load_external_timing(self.settings.interface_settings_path).debounce_seconds
        if not seconds or route(item) is not AttentionHint.DIRECT:
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
        if event.get("post_type") != "message":
            return
        if not self.transport.identity_verified:
            return
        if self.settings.qq_bot_user_id and self.transport.self_id != self.settings.qq_bot_user_id:
            return
        if event.get("self_id") and str(event["self_id"]) != str(self.transport.self_id):
            return
        item = decode(event, self_id=self.transport.self_id, owner_id=self.settings.qq_owner_user_id)
        if item is None:
            return
        reply_id = item.metadata.get("reply_to")
        if reply_id and not item.directed_to_zhaoxi:
            try:
                original = await self.transport.action("get_msg", {"message_id": int(reply_id)})
                original_data = original.get("data") or {}
                if str(original_data.get("user_id") or (original_data.get("sender") or {}).get("user_id")) == str(self.transport.self_id):
                    item.directed_to_zhaoxi = True
            except Exception as exc:
                logger.warning("reply lookup failed type=%s", type(exc).__name__)
        self.received_count += 1
        self.runtime.agent.metrics.increment("qq.message.received")
        item = await self._debounce_direct(item)
        if item is None:
            return
        response = await self.runtime.ingest(item)
        if response:
            try:
                count = await send_reply(self.transport, item, response,
                    settings=self.settings, emoji_service=getattr(self.runtime.agent, "emoji_service", None))
                await self.runtime.reply_sent(item, response, count)
                self.sent_count += count
                self.runtime.agent.metrics.increment("qq.message.sent")
            except Exception as exc:
                self.runtime.last_error = type(exc).__name__
                self.runtime.agent.metrics.increment("qq.action.failed")
                logger.warning("reply failed type=%s", type(exc).__name__)

    async def run(self):
        await self.transport.run(self.on_event)

    async def close(self):
        await self.transport.close()

    def diagnostics(self):
        return {"connected": self.transport.connected, "identity_verified": self.transport.identity_verified,
                "expected_qq": self.settings.qq_bot_user_id or None,
                "logged_in_qq": self.transport.self_id,
                "reconnect_count": self.transport.reconnect_count, "last_error": self.transport.last_error,
                "received_count": self.received_count, "sent_count": self.sent_count}
