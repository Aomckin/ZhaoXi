import json

from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.models.prompt_diagnostics import collect_prompt_diagnostics
from zhaoxi.core.message import Message, Role
from zhaoxi.models.types import ToolCall


def test_absorbed_write_result_keeps_key_id_and_does_not_rewrite_history():
    conversation = Conversation()
    original = {"success": True, "content": "创建成功" + "详细结果" * 400,
                "data": {"item": {"id": "agenda-42", "title": "明天开会", "status": "planned"},
                         "internal_payload": "大段返回" * 500}}
    conversation.add_assistant(None, tool_calls=[ToolCall(id="call-1", name="agenda_add", arguments={})])
    tool = conversation.add_tool(json.dumps(original, ensure_ascii=False),
                                 tool_call_id="call-1", name="agenda_add")
    builder = ContextBuilder("人格")
    messages = builder.build(conversation, absorbed_tool_call_ids={"call-1"})
    compacted = json.loads(messages[2].content)
    assert compacted["data"]["item"]["id"] == "agenda-42"
    assert compacted["compacted"] is True
    assert "internal_payload" not in messages[2].content
    assert conversation.messages[1].content == tool.content
    assert builder.last_compaction["tool_chars_saved"] > 1000


def test_visual_input_is_released_only_for_explicit_finalization_copy():
    conversation = Conversation()
    conversation.add_user("请看图并安排日程", images=["data:image/png;base64,AAAA"])
    builder = ContextBuilder("人格")
    assert builder.build(conversation)[1].images
    final = builder.build(conversation, release_images=True)
    assert final[1].images == []
    assert "历史图片摘要" in final[1].content
    assert builder.last_compaction["images_released"] == 1
    assert conversation.messages[0].images


def test_current_image_survives_finalization_while_old_images_are_released():
    conversation = Conversation()
    old = conversation.add_user("旧图", images=["data:image/png;base64,AAAA"])
    current = conversation.add_user("新图", images=["data:image/png;base64,BBBB"])
    builder = ContextBuilder("人格")
    initial = builder.build(conversation,
                            current_image_message_id=current.message_id)
    assert [len(message.images) for message in initial[1:]] == [0, 1]
    final = builder.build(conversation, release_images=True, preserve_current_image=True,
                          current_image_message_id=current.message_id)
    assert [len(message.images) for message in final[1:]] == [0, 1]
    assert final[-1].images[0].endswith("BBBB")
    assert builder.last_compaction["images_released"] == 1
    assert old.images and current.images

def test_context_report_has_categories_and_separates_unknown_image_cost():
    messages = [Message(role=Role.SYSTEM, content="人格", metadata={"prompt_components": [
        {"name": "system.persona", "chars": 2},
        {"name": "runtime.current_cognition", "chars": 8},
        {"name": "memory.recall", "chars": 6},
    ]}), Message(role=Role.USER, content="看图", images=["data:image/png;base64,AAAA"])]
    report = collect_prompt_diagnostics(messages, [], model="m")
    sizes = report["context_tokens_estimate"]
    assert sizes["memory_snapshot"] > 0 and sizes["retrieved_memory"] > 0
    assert sizes["image_count"] == 1 and sizes["image_tokens"] is None
    assert sizes["image_payload_chars"] > 0


def test_absorbed_decision_read_keeps_facts_and_refs_for_final_reply():
    conversation = Conversation()
    original = {"success": True, "content": "按需资料", "data": {"sources": {
        "memory": [{"ref": "memory:reading", "content": "只在阅读器上看书，不需要跨设备同步。",
                    "confidence": 1, "private_debug": "CANARY" * 500}],
        "principles": [{"ref": "principles:subscription", "principle": "先试一年",
                        "basis": ["使用习惯仍不确定"], "exceptions": ["长期使用且功能必需"]}],
        "extra": [{"ref": "extra:large", "content": "x" * 10000}] * 20}}}
    conversation.add_assistant(None, tool_calls=[ToolCall(id="read-1", name="read_decision_context", arguments={})])
    receipt = conversation.add_tool(json.dumps(original, ensure_ascii=False), tool_call_id="read-1",
                                    name="read_decision_context")
    builder = ContextBuilder("人格")
    compacted = json.loads(builder.build(conversation, absorbed_tool_call_ids={"read-1"})[-1].content)
    sources = compacted["data"]["sources"]
    assert sources["memory"][0]["ref"] == "memory:reading"
    assert "不需要跨设备同步" in sources["memory"][0]["content"]
    assert sources["principles"][0]["basis"] == ["使用习惯仍不确定"]
    assert sources["principles"][0]["exceptions"] == ["长期使用且功能必需"]
    assert "private_debug" not in sources["memory"][0]
    assert len(sources["extra"]) == 8 and len(sources["extra"][0]["content"]) == 500
    assert conversation.messages[-1].content == receipt.content
    assert compacted["compacted"] and builder.last_compaction["tool_chars_saved"] > 1000
