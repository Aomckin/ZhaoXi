import asyncio
import json
from types import SimpleNamespace

from zhaoxi.core.conversation import Conversation
from zhaoxi.core.message import Message, Role, is_user_visible_message
from zhaoxi.models.types import ToolCall
from zhaoxi.session.sqlite import SQLiteSessionStore
from zhaoxi.session.base import Session
from zhaoxi.interfaces.maintenance import PostTurnMaintenanceQueue


async def test_internal_tool_text_and_images_never_reappear_after_disk_restart(tmp_path):
    path = tmp_path / "session.db"
    store = SQLiteSessionStore(path)
    session = await store.get_or_create("local")
    session.conversation.add_user("记录")
    internal = session.conversation.add_assistant("尚未执行的承诺", tool_calls=[ToolCall(id="c", name="write", arguments={})])
    assert not is_user_visible_message(internal)
    session.conversation.add_tool("成功", tool_call_id="c", name="write")
    session.conversation.add_assistant("已记录", tool_turn=True)
    await store.save(session)
    restored = await SQLiteSessionStore(path).get("local")
    assert [item.content for item in restored.conversation.messages] == ["记录", "已记录"]
    assert restored.conversation.messages[-1].tool_turn
    assert restored.conversation.messages[-1].visibility == "conversation"
    assert len(session.conversation.messages) == 4  # live transcript remains intact


async def test_queue_is_frozen_fifo_nonblocking_and_failure_isolated(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()
    seen = []
    async def handle(payload, phase):
        if payload["request_id"] == "one" and phase == 0:
            entered.set()
            await release.wait()
        seen.append((payload["request_id"], phase, payload["text"]))
        if payload["request_id"] == "bad":
            raise ValueError("failed")
    q = PostTurnMaintenanceQueue(tmp_path / "q.db", handle)
    snapshot = {"request_id": "one", "text": "original"}
    q.enqueue("one", snapshot)
    snapshot["text"] = "mutated"
    await entered.wait()
    q.enqueue("two", {"request_id": "two", "text": "second"})
    q.enqueue("bad", {"request_id": "bad", "text": "third"})
    q.enqueue("four", {"request_id": "four", "text": "last"})
    assert seen == []
    release.set()
    await q.worker
    assert seen[:4] == [("one", 0, "original"), ("one", 1, "original"), ("two", 0, "second"), ("two", 1, "second")]
    assert {x["id"]: x["status"] for x in q.diagnostics()} == {"one":"completed", "two":"completed", "bad":"failed", "four":"completed"}
    q.enqueue("one", snapshot)
    assert len(seen) == 7


async def test_restart_recovers_queued_but_not_uncertain_writes(tmp_path):
    path = tmp_path / "q.db"
    seen = []
    async def handle(payload, phase):
        seen.append((payload["request_id"], phase))
    q = PostTurnMaintenanceQueue(path, handle, foreground_busy=lambda: True)
    q.enqueue("a", {"request_id": "a"})
    q.enqueue("b", {"request_id": "b"})
    await q.shutdown(0)
    q.db.execute("UPDATE maintenance SET status='running' WHERE id='a'")
    q.db.commit()
    q.db.close()
    restored = PostTurnMaintenanceQueue(path, handle)
    restored.start()
    await restored.worker
    assert seen == [("b", 0), ("b", 1)]
    assert {x["id"]:x["status"] for x in restored.diagnostics()}["a"] == "uncertain"


async def test_clear_and_capacity_do_not_silently_replay_old_snapshots(tmp_path):
    async def handle(payload, phase):
        raise AssertionError("cancelled work must not run")
    q = PostTurnMaintenanceQueue(tmp_path / "q.db", handle, foreground_busy=lambda: True, limit=1)
    q.enqueue("a", {})
    q.enqueue("b", {})
    assert q.diagnostics()[0]["status"] == "rejected"
    q.invalidate()
    await q.shutdown(0)
    assert {x["id"]:x["status"] for x in q.diagnostics()}["a"] == "cancelled"
