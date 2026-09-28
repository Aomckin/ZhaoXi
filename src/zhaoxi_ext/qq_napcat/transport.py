"""Forward WebSocket client with echo-correlated OneBot actions."""
import asyncio
import json
import logging
from uuid import uuid4
from websockets.asyncio.client import connect

logger = logging.getLogger("QQ_TRANSPORT")


class QQTransport:
    def __init__(self, url: str, token: str = "", reconnect_seconds: float = 5, on_state=None,
                 expected_user_id: str = ""):
        self.url, self.token, self.reconnect_seconds = url, token, reconnect_seconds
        self.socket = None
        self.pending: dict[str, asyncio.Future] = {}
        self.connected = False
        self.reconnect_count = 0
        self.last_error = None
        self.self_id = None
        self.identity_verified = False
        self._stop = False
        self.on_state = on_state
        self.expected_user_id = expected_user_id
        self._events: set[asyncio.Task] = set()

    async def action(self, name: str, params: dict | None = None, timeout: float = 10):
        if name not in {"get_login_info", "send_group_msg", "send_private_msg", "get_msg"}:
            raise ValueError("unsupported OneBot action")
        if self.socket is None:
            raise ConnectionError("QQ disconnected")
        if name in {"send_group_msg", "send_private_msg"} and not self.identity_verified:
            raise ConnectionError("QQ identity not verified")
        echo = uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.pending[echo] = future
        try:
            await self.socket.send(json.dumps({"action": name, "params": params or {}, "echo": echo}))
            return await asyncio.wait_for(future, timeout)
        finally:
            self.pending.pop(echo, None)

    async def run(self, on_event):
        self._stop = False
        while not self._stop:
            try:
                headers = {"Authorization": "Bearer " + self.token} if self.token else None
                async with connect(self.url, additional_headers=headers, open_timeout=10) as socket:
                    self.socket = socket
                    self.identity_verified = False
                    self.self_id = None
                    self.connected = True
                    if self.on_state:
                        self.on_state("connected")
                    self.last_error = None
                    async def identify():
                        try:
                            info = await self.action("get_login_info")
                            if info.get("status") != "ok":
                                raise ConnectionError("get_login_info rejected")
                            self.self_id = str((info.get("data") or {}).get("user_id") or "") or None
                            if not self.self_id:
                                raise ConnectionError("get_login_info missing user_id")
                            if self.expected_user_id and self.self_id != self.expected_user_id:
                                self.last_error = "IdentityMismatch"
                                logger.error("QQ account mismatch expected=%s actual=%s",
                                             self.expected_user_id, self.self_id)
                                await socket.close()
                            else:
                                self.identity_verified = True
                        except Exception as exc:
                            logger.warning("get_login_info failed type=%s", type(exc).__name__)
                    identify_task = asyncio.create_task(identify())
                    try:
                        async for raw in socket:
                            event = json.loads(raw)
                            echo = str(event.get("echo") or "")
                            if echo and echo in self.pending:
                                future = self.pending[echo]
                                if not future.done():
                                    future.set_result(event)
                            elif not echo:
                                if event.get("self_id") and not self.self_id:
                                    self.self_id = str(event["self_id"])
                                task = asyncio.create_task(on_event(event))
                                self._events.add(task)
                                def finish(done):
                                    self._events.discard(done)
                                    if not done.cancelled() and done.exception() is not None:
                                        logger.warning("QQ event failed type=%s", type(done.exception()).__name__)
                                task.add_done_callback(finish)
                    finally:
                        identify_task.cancel()
                        for task in self._events:
                            task.cancel()
                        await asyncio.gather(identify_task, *self._events, return_exceptions=True)
                        self._events.clear()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = type(exc).__name__
                logger.warning("QQ connection failed type=%s", type(exc).__name__)
            finally:
                if self.connected and self.on_state:
                    self.on_state("disconnected")
                self.connected = False
                self.identity_verified = False
                self.socket = None
                for future in self.pending.values():
                    if not future.done():
                        future.cancel()
                self.pending.clear()
            if not self._stop:
                self.reconnect_count += 1
                if self.on_state:
                    self.on_state("reconnect")
                await asyncio.sleep(self.reconnect_seconds)

    async def close(self):
        self._stop = True
        if self.socket is not None:
            await self.socket.close()
