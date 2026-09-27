"""NapCat source adapter; failures are isolated from the core lifecycle."""
import logging
from zhaoxi.adapters.qq.codec import decode
from zhaoxi.adapters.qq.outbound import send_reply
from zhaoxi.adapters.qq.transport import QQTransport

logger = logging.getLogger("QQ_ADAPTER")


class QQAdapter:
    def __init__(self, runtime, settings):
        self.runtime = runtime
        self.settings = settings
        self.transport = QQTransport(settings.qq_ws_url, settings.qq_access_token,
                                     settings.qq_reconnect_seconds,
                                     on_state=lambda state: runtime.agent.metrics.increment("qq." + state),
                                     expected_user_id=settings.qq_bot_user_id)
        self.received_count = 0
        self.sent_count = 0
        self.runtime.source = self

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
        response = await self.runtime.ingest(item)
        if response:
            try:
                await send_reply(self.transport, item, response)
                self.sent_count += 1
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
