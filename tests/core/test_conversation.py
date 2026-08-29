from zhaoxi.core.conversation import Conversation


def test_conversation_trims_and_clears():
    conversation = Conversation(max_messages=2)
    conversation.add_user("one")
    conversation.add_assistant("two")
    conversation.add_user("three")
    assert [message.content for message in conversation.messages] == ["two", "three"]
    conversation.clear()
    assert conversation.messages == []
