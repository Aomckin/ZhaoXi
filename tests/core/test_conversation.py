from zhaoxi.core.conversation import Conversation
from zhaoxi.core.message import Message, Role
from zhaoxi.models.types import ToolCall


def test_conversation_trims_and_clears():
    conversation = Conversation(max_messages=2)
    conversation.add_user("one")
    conversation.add_assistant("two")
    conversation.add_user("three")
    assert [message.content for message in conversation.messages] == ["two", "three"]
    conversation.clear()
    assert conversation.messages == []


def test_trimming_drops_tool_result_when_its_call_falls_out_of_history():
    conversation = Conversation(max_messages=3)
    conversation.add_assistant(None, tool_calls=[ToolCall(id="call-1", name="echo", arguments={})])
    conversation.add_tool("result", tool_call_id="call-1", name="echo")
    conversation.add_user("next")
    conversation.add_assistant("answer")

    assert [message.role for message in conversation.messages] == [Role.USER, Role.ASSISTANT]


def test_loaded_history_and_smaller_recent_window_drop_orphan_tool_results():
    call = Message(role=Role.ASSISTANT, tool_calls=[ToolCall(id="call-1", name="echo", arguments={})])
    result = Message(role=Role.TOOL, content="result", tool_call_id="call-1", name="echo")
    user = Message(role=Role.USER, content="next")
    conversation = Conversation([result, user], max_messages=3)

    assert conversation.messages == [user]
    conversation.replace([call, result, user])
    assert conversation.recent(2) == [user]
