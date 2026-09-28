import asyncio
import json
from websockets.asyncio.server import serve
from zhaoxi_ext.qq_napcat.transport import QQTransport


def test_transport_auth_echo_inbound_and_close():
    async def run():
        received = []
        authorization = []
        async def handler(socket):
            authorization.append(socket.request.headers.get("Authorization"))
            async for raw in socket:
                request = json.loads(raw)
                await socket.send(json.dumps({"status": "ok", "data": {"user_id": 42}, "echo": request["echo"]}))
                if request["action"] == "get_login_info":
                    await socket.send(json.dumps({"post_type": "meta_event", "self_id": 42}))
        async def on_event(event):
            received.append(event)
        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            transport = QQTransport(f"ws://127.0.0.1:{port}", "secret", 0.01)
            task = asyncio.create_task(transport.run(on_event))
            try:
                async with asyncio.timeout(2):
                    while not transport.connected or not received:
                        await asyncio.sleep(0.01)
                result = await transport.action("get_msg", {"message_id": 1})
                assert result["status"] == "ok"
                assert authorization == ["Bearer secret"]
                assert transport.self_id == "42"
            finally:
                await transport.close()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            assert not transport.pending
    asyncio.run(run())


def test_transport_reconnects_after_disconnect():
    async def run():
        connections = 0
        async def handler(socket):
            nonlocal connections
            connections += 1
            await socket.close()
        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            transport = QQTransport(f"ws://127.0.0.1:{port}", reconnect_seconds=0.01)
            async def ignore(_):
                pass
            task = asyncio.create_task(transport.run(ignore))
            try:
                async with asyncio.timeout(2):
                    while connections < 2:
                        await asyncio.sleep(0.01)
                assert transport.reconnect_count >= 1
            finally:
                await transport.close()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


def test_transport_rejects_wrong_bot_account():
    async def run():
        async def handler(socket):
            async for raw in socket:
                request = json.loads(raw)
                await socket.send(json.dumps({"status": "ok", "data": {"user_id": 3768425246},
                                              "echo": request["echo"]}))
        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            transport = QQTransport(f"ws://127.0.0.1:{port}", expected_user_id="2899706784",
                                    reconnect_seconds=1)
            async def ignore(_):
                raise AssertionError("wrong bot event must not be delivered")
            task = asyncio.create_task(transport.run(ignore))
            try:
                async with asyncio.timeout(2):
                    while transport.last_error != "IdentityMismatch":
                        await asyncio.sleep(0.01)
                assert not transport.identity_verified
                try:
                    await transport.action("send_private_msg", {"user_id": 1, "message": "x"})
                except ConnectionError:
                    pass
                else:
                    raise AssertionError("wrong bot was allowed to send")
            finally:
                await transport.close()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())
