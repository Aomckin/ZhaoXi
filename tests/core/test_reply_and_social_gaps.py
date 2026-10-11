"""17:15 regression: real no-hit retrieval and malformed closing cannot masquerade as success."""
import json

import pytest
from test_loop_safety import agent, call, Probe, correlation
from zhaoxi.cognitive_stream import ExperienceStream
from zhaoxi.models.types import ModelResponse, ToolCall
from zhaoxi.observability import action_trace_scope
from zhaoxi.tools.base import ToolResult
from zhaoxi.tools.builtin.social_context import ReadSocialContextTool

BAD = '{"type":"json_object"}'
BODY = "唔，保存的群聊里没搜到这条，但记忆里的线索还在。"


def final(body=BODY):
    return ModelResponse(content=json.dumps({"reply":body, "awareness":{"mode":"NONE"}}, ensure_ascii=False), finish_reason="stop")


@pytest.mark.parametrize("config_echo", [False, True])
async def test_two_empty_searches_do_not_block_sibling_memory_lookup_or_force_closing(tmp_path, config_echo):
    batch = ModelResponse(tool_calls=[
        ToolCall(id="empty-1", name="read_social_context", arguments={"query":"虚拟桌宠模拟器", "group_id":"A"}),
        ToolCall(id="empty-2", name="read_social_context", arguments={"query":"VPet", "group_id":"A"}),
        ToolCall(id="memory", name="search_memories", arguments={"query":"桌宠"}),
    ])
    memory = Probe([ToolResult(success=True, content="保存的桌宠记忆", data={"fact":"桌宠"})])
    memory.name = "search_memories"
    replies = [batch, ModelResponse(content=BAD, finish_reason="stop"), ModelResponse(content=json.dumps({"reply":BODY}, ensure_ascii=False))] if config_echo else [batch, final()]
    a, provider = agent(replies, memory)
    a.decision_mode = "agency"
    a.registry.register(ReadSocialContextTool(ExperienceStream(tmp_path / "experience.db")))
    with action_trace_scope() as trace:
        result = await a.run("虚拟桌宠模拟器，去回想一下", require_tool_call=True, required_tool="search_memories")
    assert memory.calls == ["桌宠"]
    assert len(provider.calls) == (3 if config_echo else 2) and result.content == BODY and result.result_status == "completed"
    assert trace.repair_round == int(config_echo)
    assert trace.tool_locked == [] and trace.tool_retry_count == 0
    assert trace.forced_finalization_reason != "tool_failure_limit"
    assert not any(e.event_type in {"tool_call_blocked", "tool_repair_limit"} for e in trace.events)
    searches = [json.loads(m.content) for m in a.conversation.messages if m.role.value == "tool" and "not_found" in m.content]
    assert len(searches) == 2 and all(s["success"] and s["error"] is None for s in searches)


@pytest.mark.parametrize("repair_succeeds", [False, True])
async def test_config_echo_triggers_one_body_only_repair_without_replaying_success(repair_succeeds):
    tool = Probe([ToolResult(success=True, content="真实结果", data={"fact":"已核实"})])
    repaired = ModelResponse(content=json.dumps({"reply":BODY}, ensure_ascii=False)) if repair_succeeds else ModelResponse(content=BAD)
    a, provider = agent([call(), ModelResponse(content=BAD, finish_reason="stop"), repaired], tool)
    a.decision_mode = "agency"
    with action_trace_scope() as trace:
        result = await a.run("核验已有线索")
    assert tool.calls == ["q"] and len(provider.calls) == 3
    assert provider.tool_schemas[-1] is None and trace.repair_round == 1
    assert any(e.event_type == "reply_recovery_requested" for e in trace.events)
    assert any(e.event_type == "main_reply_protocol" and e.error_code == "invalid_reply_protocol" for e in trace.events)
    assert BAD not in result.content
    assert all(BAD not in (m.content or "") for m in a.conversation.messages if m.role.value == "assistant")
    if repair_succeeds:
        assert result.content == BODY and trace.response_status == "succeeded"
    else:
        assert trace.response_status == "failed"
        assert "已执行的操作和结果均已保留" in result.content


async def test_config_echo_at_final_step_reports_failure_without_extending_budget():
    tool = Probe([ToolResult(success=True, content="真实结果")])
    a, provider = agent([call(), ModelResponse(content=BAD, finish_reason="stop")], tool)
    a.decision_mode = "agency"
    a.max_steps = 2
    with action_trace_scope() as trace:
        result = await a.run("核验结果")
    assert tool.calls == ["q"] and len(provider.calls) == 2
    assert trace.response_status == "failed" and trace.repair_round == 0
    assert BAD not in result.content and "模型未能生成完整正文" in result.content
