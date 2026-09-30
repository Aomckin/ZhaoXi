"""Task-book acceptance and integration checks for Fast Gate 2.0."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from conftest import FakeProvider
from zhaoxi.cognitive.coordinator import CognitiveCoordinator
from zhaoxi.cognitive.fast_gate import FastDialogueGate, FastGateLane
from zhaoxi.cognitive.router import CognitiveRouter, CognitiveRoute
from zhaoxi.config import Settings
from zhaoxi.config.fast_gate import FastGateConfig
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.models.resilient import ResilientProvider
from zhaoxi.models.types import ModelResponse, ToolCall
from zhaoxi.observability import action_trace_scope
from zhaoxi.reliability import CorrelationContext, correlation_scope
from zhaoxi.reliability.retry import provider_budget_scope
from zhaoxi.tools.base import Tool, ToolResult
from zhaoxi.tools.builtin import create_builtin_tools
from zhaoxi.tools.registry import ToolRegistry
from pydantic import BaseModel


def routed(route, **kwargs):
    return ModelResponse(tool_calls=[ToolCall(id="route", name="route_cognition",
        arguments={"route": route, "reason": "test verdict", **kwargs})])


def agent_for(provider):
    registry = ToolRegistry()
    for tool in create_builtin_tools():
        registry.register(tool)
    agent = ZhaoxiAgent(provider=provider, registry=registry, context_builder=ContextBuilder("朝汐"))
    agent.cognitive = CognitiveCoordinator(agent=agent, router=CognitiveRouter(provider),
                                            fast_gate=FastDialogueGate())
    return agent


@pytest.mark.parametrize(("message", "context", "lane"), [
    ("小金毛？", {}, FastGateLane.FAST_CONFIDENT),
    ("最近秋招真没啥结果", {"current_cognition": "秋招仍是近期主线", "current_topics": ["秋招"]}, FastGateLane.FAST_CONFIDENT),
    ("书馆里未来开发计划9.21版，自己去看", {}, FastGateLane.HEAVY_CONFIDENT),
    ("去补一份吧，把这个 bug 记录起来，我等下处理", {"recent_context": "assistant: 缺一份 bug 记录文件"}, FastGateLane.HEAVY_CONFIDENT),
    ("LifeHUD 这个界面看着有点怪", {"capability_groups": ["lifehud"]}, FastGateLane.FAST_CONFIDENT),
    ("亚信上次具体问了我哪些题？", {}, FastGateLane.HEAVY_CONFIDENT),
    ("之前那个你觉得怎么样？", {}, FastGateLane.AMBIGUOUS),
])
def test_task_book_cases(message, context, lane):
    decision = FastDialogueGate().decide(message, **context)
    assert decision.lane is lane
    details = decision.diagnostics()
    assert details["fast_gate_version"] == 2
    assert details["fast_gate_signals"]
    if lane is FastGateLane.FAST_CONFIDENT:
        assert decision.fast_positive_evidence
    elif lane is FastGateLane.HEAVY_CONFIDENT:
        assert decision.heavy_evidence


def test_journal_is_positive_evidence_but_not_permission_to_act():
    gate = FastDialogueGate()
    context = {"current_cognition": "秋招缺少实质性结果", "current_topics": ["秋招"]}
    chat = gate.decide("最近秋招真没啥结果", **context)
    action = gate.decide("把秋招结果记录起来", **context)
    assert chat.signals.current_cognition_sufficient
    assert chat.signals.current_cognition_relevance >= 0.8
    assert action.lane is FastGateLane.HEAVY_CONFIDENT
    assert not action.signals.current_cognition_sufficient


def test_recent_context_distinguishes_acknowledgement_from_unfinished_action():
    gate = FastDialogueGate()
    chat = gate.decide("确实舒服多了", recent_context="assistant: Fast Chat 现在终于快了")
    action = gate.decide("去补一份吧，把这个 bug 记录起来，我等下处理",
                         recent_context="assistant: 缺一份 bug 记录文件")
    assert chat.lane is FastGateLane.FAST_CONFIDENT
    assert chat.signals.recent_context_sufficient
    assert action.signals.continuation_confidence >= 0.8
    assert action.signals.action_side_effect_confidence >= 0.8


@pytest.mark.parametrize("kwargs", [{"images": ["image"]}, {"pending_permission": True}])
def test_hard_constraints_win_over_positive_chat(kwargs):
    decision = FastDialogueGate().decide("小金毛？", **kwargs)
    assert decision.lane is FastGateLane.HEAVY_CONFIDENT


def test_unknown_sentence_does_not_default_to_fast():
    assert FastDialogueGate().decide("冰柜里的第八个").lane is FastGateLane.AMBIGUOUS
    assert FastDialogueGate().decide("LifeHUD").lane is FastGateLane.AMBIGUOUS
    assert FastDialogueGate().decide("小金毛？", signal_errors=["context_unavailable"]).lane is FastGateLane.AMBIGUOUS


def test_thresholds_are_validated_and_loaded_from_configuration(monkeypatch):
    monkeypatch.setenv("ZHAOXI_FAST_GATE", '{"fast_min_score":0.99,"strong_threshold":0.85}')
    config = Settings(_env_file=None).fast_gate
    assert config.strong_threshold == 0.85
    assert FastDialogueGate(config).decide("小金毛？").lane is FastGateLane.AMBIGUOUS
    with pytest.raises(ValueError):
        FastGateConfig(strong_threshold=1.1)


async def test_confident_chat_keeps_one_call_and_explains_gate_metrics():
    inner = FakeProvider([ModelResponse(content="在呢。")])
    agent = agent_for(ResilientProvider([inner]))
    with correlation_scope(CorrelationContext(trace_id="gate-v2", request_id="gate-v2")), action_trace_scope() as trace, provider_budget_scope(4):
        response = await agent.run_natural("小金毛？")
        metrics = trace.metrics()
    assert response.route is CognitiveRoute.FAST_CHAT
    assert metrics["foreground_llm_calls"] == 1
    assert metrics["router_llm_calls"] == 0
    assert metrics["fast_gate_decision"] == "FAST_CONFIDENT"
    assert metrics["fast_gate_version"] == 2
    assert not metrics["router_required"]
    assert metrics["fast_positive_evidence"]
    assert len(inner.calls) == 1


async def test_ambiguous_router_can_choose_fast_with_two_calls_and_metrics():
    inner = FakeProvider([routed("fast_chat"), ModelResponse(content="我觉得还可以。")])
    agent = agent_for(ResilientProvider([inner]))
    with correlation_scope(CorrelationContext(trace_id="ambiguous", request_id="ambiguous")), action_trace_scope() as trace, provider_budget_scope(4):
        response = await agent.run_natural("之前那个你觉得怎么样？")
        metrics = trace.metrics()
    assert response.route is CognitiveRoute.FAST_CHAT
    assert len(inner.calls) == 2
    assert inner.tool_schemas[0][0]["function"]["name"] == "route_cognition"
    assert inner.tool_schemas[1] is None
    assert metrics["fast_gate_decision"] == "AMBIGUOUS"
    assert metrics["router_required"] and metrics["router_override"]
    assert metrics["router_final_lane"] == "fast_chat"
    assert metrics["router_to_fast_count"] == 1
    assert metrics["runtime_lane"] == "fast"
    assert metrics["foreground_llm_calls"] == 2


async def test_router_fast_verdict_cannot_hide_required_side_effect():
    provider = FakeProvider([routed("fast_chat", requires_tool_call=True)])
    decision = await CognitiveRouter(provider).route("请处理这个请求")
    assert decision.route is CognitiveRoute.TOOL
    assert decision.requires_tool_call


async def test_router_fast_commitment_escalates_without_second_router():
    provider = FakeProvider([routed("fast_chat"), ModelResponse(content="我现在去查一下。"),
        ModelResponse(tool_calls=[ToolCall(id="time", name="current_time", arguments={})]),
        ModelResponse(content="查好了。")])
    agent = agent_for(provider)
    response = await agent.run_natural("之前那个你觉得怎么样？")
    assert response.route is CognitiveRoute.TOOL
    assert len(provider.calls) == 4
    assert sum(bool(schemas and schemas[0]["function"]["name"] == "route_cognition") for schemas in provider.tool_schemas) == 1


class EmptyInput(BaseModel):
    pass


class LifeTool(Tool):
    name = "lifehud"
    group = "lifehud"
    description = "记录或查询生活数据"
    aliases = ("LifeHUD",)
    input_model = EmptyInput
    async def execute(self, arguments):
        return ToolResult(success=True, content="test")


async def test_live_capability_index_distinguishes_ui_comment_from_record_request():
    provider = FakeProvider([ModelResponse(content="界面确实有些奇怪。")])
    agent = agent_for(provider)
    agent.registry.register(LifeTool())
    response = await agent.run_natural("LifeHUD 这个界面看着有点怪")
    assert response.route is CognitiveRoute.FAST_CHAT
    assert len(provider.calls) == 1
    context = agent.cognitive._fast_gate_context("把今晚吃的记进 LifeHUD", "")
    decision = agent.cognitive.fast_gate.decide("把今晚吃的记进 LifeHUD", **context)
    assert decision.signals.capability_match >= 0.8
    assert decision.lane is FastGateLane.HEAVY_CONFIDENT


async def test_confident_actions_skip_router_and_require_real_tool_path():
    provider = FakeProvider([ModelResponse(tool_calls=[ToolCall(id="time", name="current_time", arguments={})]),
                             ModelResponse(content="记录已补。")])
    agent = agent_for(provider)
    agent.conversation.add_assistant("缺一份 bug 记录文件")
    agent.cognitive.router.route = AsyncMock(side_effect=AssertionError("should not route"))
    agent.run = AsyncMock(wraps=agent.run)
    response = await agent.run_natural("去补一份吧，把这个 bug 记录起来，我等下处理")
    assert response.route is CognitiveRoute.TOOL
    agent.cognitive.router.route.assert_not_awaited()
    assert "FAST_CHAT" not in provider.calls[0][0].content
    assert agent.run.call_args.kwargs["require_tool_call"] is True
    assert any(message.role.value == "tool" for message in agent.conversation.messages)


async def test_current_trigger_cannot_supply_its_own_recent_evidence(tmp_path):
    from zhaoxi.cognitive_stream import ExperienceStream
    from zhaoxi.cognitive_stream.ingress import CognitiveIngress
    from zhaoxi.cognitive_stream.turn import CognitiveTurnContext, set_current_turn, reset_current_turn
    provider = FakeProvider([])
    agent = agent_for(provider)
    stream = ExperienceStream(tmp_path / "experience.db")
    agent.experience_stream = stream
    event = CognitiveIngress(stream).desktop("之前那个你觉得怎么样？")
    token = set_current_turn(CognitiveTurnContext(trigger_event=event))
    try:
        recent = agent.cognitive._recent_routing_context()
    finally:
        reset_current_turn(token)
    assert recent == ""


@pytest.mark.parametrize("message", ["我想了解那个文件", "我想确认这个结果", "今天想知道更多细节", "我需要那份资料"])
def test_information_seeking_is_not_a_self_contained_social_statement(message):
    assert FastDialogueGate().decide(message).lane is FastGateLane.AMBIGUOUS


async def test_router_and_debug_cannot_bypass_pending_permission():
    from zhaoxi.core.agent import AgentResponse
    provider = FakeProvider([routed("fast_chat")])
    agent = agent_for(provider)
    agent._pending_permissions["pending"] = object()
    agent.cognitive.force_fast_chat = True
    agent.run_direct = AsyncMock(return_value=AgentResponse(content="等待确认。", request_id="p", steps=1))
    agent.cognitive.fast_chat.run_fast_chat = AsyncMock(side_effect=AssertionError("must not fast"))
    with correlation_scope(CorrelationContext(trace_id="permission", request_id="permission")), action_trace_scope() as trace:
        response = await agent.cognitive.run("小金毛？")
        metrics = trace.metrics()
    assert response.route is CognitiveRoute.DIRECT
    assert metrics["fast_gate_decision"] == "HEAVY_CONFIDENT"
    assert metrics["router_final_lane"] == "direct"
    assert not metrics["router_override"]
    agent.cognitive.fast_chat.run_fast_chat.assert_not_awaited()


def test_continuing_social_statement_is_not_a_choice_decision():
    gate = FastDialogueGate()
    assert gate.decide("我这几天还是在弄朝汐").lane is FastGateLane.FAST_CONFIDENT
    assert gate.decide("我应该接这个工作还是继续找？").lane is FastGateLane.HEAVY_CONFIDENT
    assert gate.decide("读取计划.md").lane is FastGateLane.HEAVY_CONFIDENT


def test_failed_capability_collection_delegates_instead_of_defaulting_to_fast(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("unavailable index")
    monkeypatch.setattr("zhaoxi.tools.router.safe_resolve_tool_context", broken)
    agent = agent_for(FakeProvider([]))
    context = agent.cognitive._fast_gate_context("小金毛？", "")
    decision = agent.cognitive.fast_gate.decide("小金毛？", **context)
    assert decision.lane is FastGateLane.AMBIGUOUS
    assert decision.signals.signal_errors == ("capability_index:RuntimeError",)
