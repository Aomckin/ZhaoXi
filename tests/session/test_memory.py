import pytest

from zhaoxi.session.memory import InMemorySessionStore


@pytest.mark.asyncio
async def test_in_memory_session_lifecycle():
    store = InMemorySessionStore()
    session = await store.create()
    session.conversation.add_user("hello")
    await store.save(session)
    assert (await store.get(session.id)).conversation.messages[0].content == "hello"
    assert [item.id for item in await store.list()] == [session.id]
    assert await store.delete(session.id)
    assert await store.get(session.id) is None
