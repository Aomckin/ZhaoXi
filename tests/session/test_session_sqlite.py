import pytest

from zhaoxi.core.message import Message, Role
from zhaoxi.session.sqlite import SQLiteSessionStore


@pytest.mark.asyncio
async def test_sqlite_session_persists_only_bounded_user_visible_text(tmp_path):
    path = tmp_path / "session.db"
    store = SQLiteSessionStore(path, max_messages=2)
    session = await store.create()
    session.conversation.add_user("one")
    session.conversation.add_tool("secret payload", tool_call_id="call", name="tool")
    session.conversation.add(Message(role=Role.ASSISTANT, content="two", metadata={"secret": "x"}))
    await store.save(session)

    restored = await SQLiteSessionStore(path, max_messages=2).get(session.id)
    assert [(item.role.value, item.content) for item in restored.conversation.messages] == [
        ("user", "one"),
        ("assistant", "two")
    ]
    assert restored.conversation.messages[1].metadata == {}


@pytest.mark.asyncio
async def test_sqlite_session_delete_survives_restart(tmp_path):
    path = tmp_path / "session.db"
    store = SQLiteSessionStore(path)
    session = await store.create()
    assert await store.delete(session.id)
    assert await SQLiteSessionStore(path).get(session.id) is None


@pytest.mark.asyncio
async def test_sqlite_session_alarms_without_dropping_polluted_assistant_content(tmp_path, caplog):
    store = SQLiteSessionStore(tmp_path / "session.db")
    session = await store.create()
    session.conversation.add(Message(role=Role.ASSISTANT, content="正常正文。\nuser: 内部转录"))

    await store.save(session)

    restored = await store.get(session.id)
    assert restored.conversation.messages[-1].content == "正常正文。\nuser: 内部转录"
    assert "assistant persistence contamination preserved" in caplog.text
