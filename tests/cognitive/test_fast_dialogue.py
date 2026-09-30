"""v1.4.1 fast dialogue lane and standard finalization regression tests."""

import pytest

from conftest import FakeProvider
from zhaoxi.cognitive.coordinator import CognitiveCoordinator
from zhaoxi.cognitive.fast_gate import FastDialogueGate, FastGateLane
from zhaoxi.cognitive.router import CognitiveRoute, CognitiveRouter
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.models.resilient import ResilientProvider
from zhaoxi.models.types import ModelResponse, ToolCall
from zhaoxi.observability import action_trace_scope
from zhaoxi.reliability import CorrelationContext, correlation_scope
from zhaoxi.reliability.retry import provider_budget_scope
from zhaoxi.tools.builtin import create_builtin_tools
from zhaoxi.tools.registry import ToolRegistry


def call(name, arguments=None):
    return ModelResponse(tool_calls=[ToolCall(id=name, name=name, arguments=arguments or {})])


def make_agent(provider):
    registry = ToolRegistry()
    for tool in create_builtin_tools():
        registry.register(tool)
    return ZhaoxiAgent(
        provider=provider,
        registry=registry,
        context_builder=ContextBuilder("你是朝汐。"),
        conversation=Conversation(),
    )


@pytest.mark.parametrize("text", ["小金毛？", "今天真热啊", "我刚吃完饭", "在吗？", "哈哈哈哈"])
def test_social_turns_are_fast_by_default(text):
    decision = FastDialogueGate().decide(text)
    assert decision.eligible is True
    assert decision.reason == "safe_conversation"


@pytest.mark.parametrize("text", [
    "刚刚那两条继续", "记一下这件事", "你还记得上次吗", "这个值不值得买",
    "帮我查一下最新消息", "先查今天记录，再补缺失的，最后重新核对",
])
def test_fast_gate_rejects_turns_that_need_heavier_runtime(text):
    decision = FastDialogueGate().decide(text)
    assert decision.eligible is False
    assert decision.lane in {FastGateLane.AMBIGUOUS, FastGateLane.HEAVY_CONFIDENT}
    assert decision.reason


async def test_fast_chat_uses_one_tool_free_call_without_memory_or_router():
    provider = FakeProvider([ModelResponse(content="在呢，怎么突然叫我？")])
    agent = make_agent(provider)
    agent.cognitive = CognitiveCoordinator(
        agent=agent,
        router=CognitiveRouter(provider),
        fast_gate=FastDialogueGate(),
    )

    response = await agent.run_natural("小金毛？")

    assert response.route is CognitiveRoute.FAST_CHAT
    assert response.content == "在呢，怎么突然叫我？"
    assert len(provider.calls) == 1
    assert provider.tool_schemas == [None]
    assert "FAST_CHAT" in provider.calls[0][0].content
    assert [message.content for message in provider.calls[0] if message.role.value == "user"] == ["小金毛？"]


async def test_social_short_turn_does_not_resume_recent_tool_task():
    provider = FakeProvider([ModelResponse(content="在呢。")])
    agent = make_agent(provider)
    agent.conversation.add_user("帮我查 LifeHUD")
    agent.conversation.add_assistant("正在处理", tool_turn=True)
    agent.cognitive = CognitiveCoordinator(
        agent=agent,
        router=CognitiveRouter(provider),
        fast_gate=FastDialogueGate(),
    )

    response = await agent.run_natural("在吗？")

    assert response.route is CognitiveRoute.FAST_CHAT
    assert len(provider.calls) == 1
    assert provider.tool_schemas[0] is None


async def test_explicit_continuation_still_uses_router():
    provider = FakeProvider([
        call("route_cognition", {"route": "direct", "reason": "承接上一轮"}),
        ModelResponse(content="好，接着来。"),
    ])
    agent = make_agent(provider)
    agent.cognitive = CognitiveCoordinator(
        agent=agent,
        router=CognitiveRouter(provider),
        fast_gate=FastDialogueGate(),
    )

    response = await agent.run_natural("刚刚那两条继续")

    assert response.route is CognitiveRoute.DIRECT
    assert len(provider.calls) == 2
    assert provider.tool_schemas[0][0]["function"]["name"] == "route_cognition"


async def test_successful_business_tool_keeps_tools_available():
    provider = FakeProvider([
        call("current_time"),
        ModelResponse(content="现在已经查到了。"),
    ])
    agent = make_agent(provider)

    response = await agent.run("现在几点？", require_tool_call=True, required_tool="current_time")

    assert response.used_tool_path is True
    assert len(provider.calls) == 2
    assert provider.tool_schemas[0]
    assert provider.tool_schemas[1]


async def test_explicit_single_tool_request_skips_router_and_stops_after_model_reply():
    provider = FakeProvider([
        call("current_time"),
        ModelResponse(content="现在已经查到了。"),
    ])
    agent = make_agent(provider)
    agent.cognitive = CognitiveCoordinator(
        agent=agent,
        router=CognitiveRouter(provider),
        fast_gate=FastDialogueGate(),
    )

    response = await agent.run_natural("现在几点？")

    assert response.route is CognitiveRoute.TOOL
    assert len(provider.calls) == 2
    assert provider.tool_schemas[0]
    assert provider.tool_schemas[1]


async def test_fast_action_commitment_escalates_only_once():
    provider = FakeProvider([
        ModelResponse(content="我现在去查一下。"),
        call("current_time"),
        ModelResponse(content="已经查完了。"),
    ])
    agent = make_agent(provider)
    agent.cognitive = CognitiveCoordinator(
        agent=agent,
        router=CognitiveRouter(provider),
        fast_gate=FastDialogueGate(),
    )

    response = await agent.run_natural("小金毛？")

    assert response.route is CognitiveRoute.TOOL
    assert len(provider.calls) == 3
    assert provider.tool_schemas[0] is None
    assert provider.tool_schemas[-1]

async def test_fast_trace_reports_v141_lane_counters():
    inner = FakeProvider([ModelResponse(content="在呢。")])
    provider = ResilientProvider([inner])
    agent = make_agent(provider)
    agent.cognitive = CognitiveCoordinator(
        agent=agent,
        router=CognitiveRouter(provider),
        fast_gate=FastDialogueGate(),
    )

    with correlation_scope(CorrelationContext(trace_id="fast", request_id="fast")), \
            action_trace_scope() as trace, provider_budget_scope(4):
        response = await agent.run_natural("在吗？")
        metrics = trace.metrics()

    assert response.route is CognitiveRoute.FAST_CHAT
    assert metrics["runtime_lane"] == "fast"
    assert metrics["route_source"] == "fast_gate"
    assert metrics["fast_gate_reason"] == "safe_conversation"
    assert metrics["foreground_llm_calls"] == 1
    assert metrics["background_llm_calls"] == 0
    assert metrics["router_llm_calls"] == 0
    assert metrics["agent_llm_calls"] == 1
    assert metrics["memory_search_count"] == 0
    assert metrics["tool_rounds"] == 0
    assert metrics["catalog_inspections"] == 0

async def test_debug_force_fast_bypasses_gate_but_preserves_one_way_escalation():
    provider = FakeProvider([ModelResponse(content="我现在去查一下。"), call("current_time"),
                             ModelResponse(content="查过了。")])
    agent = make_agent(provider)
    agent.cognitive = CognitiveCoordinator(
        agent=agent,
        router=CognitiveRouter(provider),
        fast_gate=FastDialogueGate(),
    )
    agent.cognitive.force_fast_chat = True

    response = await agent.run_natural("帮我查一下最新消息")

    assert response.route is CognitiveRoute.TOOL
    assert response.content == "查过了。"
    assert len(provider.calls) == 3
    assert provider.tool_schemas[0] is None
    assert all("我现在去查一下。" != m.content for m in agent.conversation.messages)

async def test_fast_chat_uses_journal_as_context_without_resuming_tasks(tmp_path):
    from zhaoxi.current_cognition import CurrentCognitionService, CurrentCognitionStore
    from zhaoxi.current_cognition.service import CurrentCognitionPatch
    cognition = CurrentCognitionService(CurrentCognitionStore(tmp_path / "cognition.db"))
    cognition.apply(CurrentCognitionPatch(decision="UPDATE", evidence_message_ids=["u1"],
        overview={"action": "replace", "value": "这几天秋招仍在推进，LifeHUD 饮食记录也在整理。"}),
        source_by_id={"u1": "user"},
        evidence_by_id={"u1": "这几天秋招仍在推进，LifeHUD 饮食记录也在整理"},
        last_message_id="u1")
    provider = FakeProvider([ModelResponse(content="在呢。"), ModelResponse(content="是啊，秋招这条线还挂着。")])
    agent = make_agent(provider)
    agent.context_builder.current_cognition_service = cognition
    agent.cognitive = CognitiveCoordinator(agent=agent, router=CognitiveRouter(provider),
                                            fast_gate=FastDialogueGate())
    first = await agent.run_natural("小金毛？")
    second = await agent.run_natural("最近感觉秋招真没啥结果")
    assert first.route is second.route is CognitiveRoute.FAST_CHAT
    assert len(provider.calls) == 2
    assert provider.tool_schemas == [None, None]
    assert "LifeHUD" in provider.calls[0][0].content
    assert "秋招" in provider.calls[1][0].content
    assert FastDialogueGate().decide("我上次亚信面试具体问了啥？").eligible is False


async def test_fast_visual_followup_replays_latest_historical_thumbnail_from_stream(tmp_path):
    import base64
    from io import BytesIO
    from PIL import Image
    from zhaoxi.cognitive_stream import ExperienceStream
    from zhaoxi.cognitive_stream.ingress import CognitiveIngress
    from zhaoxi.cognitive_stream.models import CognitiveEventType

    output = BytesIO()
    Image.new("RGB", (1600, 1000), (20, 90, 150)).save(output, format="PNG")
    original = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")
    stream = ExperienceStream(tmp_path / "experience.db")
    ingress = CognitiveIngress(stream)
    picture = ingress.desktop("这张图呢？", images=[original], channel="web")
    for index in range(9):
        ingress.record(CognitiveEventType.ASSISTANT_REPLY, f"回复 {index}",
                       source="agent", channel="web", turn_id=picture.event_id,
                       reply_to_event_id=picture.event_id)
    question = "上一张图还能看见吗？"
    ingress.desktop(question, channel="web")
    provider = FakeProvider([ModelResponse(content="能看到。")])
    agent = make_agent(provider)
    agent.experience_stream = stream
    agent.cognitive = CognitiveCoordinator(agent=agent, router=CognitiveRouter(provider),
                                            fast_gate=FastDialogueGate())

    # Exercise the visual runtime independently of Gate's ambiguity decision.
    agent.cognitive.force_fast_chat = True
    response = await agent.run_natural(question)

    assert response.route is CognitiveRoute.FAST_CHAT
    assert len(provider.calls) == 1
    assert provider.tool_schemas == [None]
    pictured = [message for message in provider.calls[0] if message.images]
    assert len(pictured) == 1
    assert pictured[0].content == "这张图呢？"
    assert pictured[0].images[0].startswith("data:image/jpeg;base64,")
    assert pictured[0].images[0] != original
    with Image.open(BytesIO(base64.b64decode(pictured[0].images[0].partition(",")[2]))) as image:
        assert max(image.size) <= 512
    assert [part.url for part in stream.get(picture.event_id).parts] == [original]
