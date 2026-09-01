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
        ("assistant", "two")
    ]
    assert restored.conversation.messages[0].metadata == {}


@pytest.mark.asyncio
async def test_sqlite_session_delete_survives_restart(tmp_path):
    path = tmp_path / "session.db"
    store = SQLiteSessionStore(path)
    session = await store.create()
    assert await store.delete(session.id)
    assert await SQLiteSessionStore(path).get(session.id) is None
