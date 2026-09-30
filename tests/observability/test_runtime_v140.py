"""Runtime metrics and progressive reply boundaries."""
import pytest
from types import SimpleNamespace

from conftest import FakeProvider
from zhaoxi.config.settings import Settings
from zhaoxi.errors import AgentLoopError, ProviderError
from zhaoxi.models.resilient import ResilientProvider
from zhaoxi.reliability.retry import provider_budget_scope
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.interfaces.gateway import InterfaceGateway
from zhaoxi.interfaces.models import InterfaceChannel, UnifiedMessage
from zhaoxi.models.types import ModelResponse, ToolCall
from zhaoxi.observability import ActionTrace
from zhaoxi.planner.models import Goal
from zhaoxi.planner.trace import TraceRecorder
from zhaoxi.reliability import CorrelationContext, correlation_scope
from zhaoxi.observability import action_trace_scope
from zhaoxi.tools.registry import ToolRegistry


def test_interim_event_is_distinct_and_bounded():
    events = []
    trace = ActionTrace("trace", "request", events.append)
    trace.interim_threshold_seconds = 0
    trace.current_step = 2
    assert trace.emit_interim("我先把记录对一下～")
    assert not trace.emit_interim("还在处理～")
    assert trace.first_reply_ms is not None
    assert trace.interim_replies == 1
    assert [event["type"] for event in events].count("interim_reply") == 1
    assert events[-1]["terminates_turn"] is False
    trace.finish()
    metrics = trace.metrics()
    assert metrics["ttfr_ms"] <= metrics["total_ms"]
    assert metrics["final_response_ms"] == metrics["total_ms"]
    assert metrics["interim_replies"] == 1
    assert metrics["finished_at"]


def test_runtime_metrics_include_actual_memory_candidate_scores_without_logging_content():
    events = []
    trace = ActionTrace("trace", "request", events.append)
    candidate = SimpleNamespace(
        record=SimpleNamespace(
            id="memory-1", content="用户偏好在晚上写代码",
            kind=SimpleNamespace(value="semantic"),
            status=SimpleNamespace(value="active"),
        ),
        cluster=SimpleNamespace(topic="开发习惯"), score=0.8765,
        contextual_relevance=0.8, text_score=0.7, semantic_score=0.6,
        graph_score=0.5, time_score=0.4, activation_score=0.3,
        importance_score=0.2, why_selected=["text=0.700", "graph=0.500"],
    )
    trace.record_memory_candidates([candidate])
    snapshot = trace.metrics()["memory_candidates"][0]
    assert snapshot["content"] == "用户偏好在晚上写代码"
    assert snapshot["final_score"] == 0.8765
    assert snapshot["graph_score"] == 0.5
    assert snapshot["why_selected"] == ["text=0.700", "graph=0.500"]
    trace.finish()
    final = events[-1]["event"]["metadata"]["runtime_metrics"]
    assert final["memory_hits"] == 0
    assert "memory_candidates" not in final


def test_second_planner_reply_requires_progress():
    trace = ActionTrace("trace", "request", lambda event: None)
    trace.interim_threshold_seconds = 0
    trace.planner_used = True
    assert trace.emit_interim("我先核对前面的记录～", reason="planner")
    assert not trace.emit_interim("我继续看看～", reason="planner")
    trace.emit("planner_step_completed", "planner", "success", "计划进度已更新")
    assert trace.emit_interim("记录核对完了，接下来检查 LifeHUD～",
                              reason="planner", progress="记录核对完成")
    assert trace.interim_replies == 2
    assert not trace.emit_interim("第三次", reason="planner", progress="更多进展")


async def test_agent_records_candidates_from_the_real_context_retrieval():
    candidate = SimpleNamespace(
        record=SimpleNamespace(
            id="memory-actual", content="晚间开发效率更高",
            kind=SimpleNamespace(value="semantic"),
            status=SimpleNamespace(value="active"),
        ),
        cluster=None, score=0.91, contextual_relevance=0.82,
        text_score=0.73, semantic_score=0.64, graph_score=0.0,
        time_score=0.55, activation_score=0.44, importance_score=0.66,
        why_selected=["embedding=0.640"],
    )
    class Retrieval:
        async def retrieve(self, text):
            return [candidate]
        def format(self, results):
            return "相关记忆：晚间开发效率更高"
    agent = ZhaoxiAgent(
        provider=FakeProvider([ModelResponse(content="记得。")]),
        registry=ToolRegistry(),
        context_builder=ContextBuilder("你是朝汐。", memory_retriever=Retrieval()),
    )
    gateway = InterfaceGateway(agent)
    await gateway.chat(UnifiedMessage(
        request_id="memory-candidates", channel=InterfaceChannel.WEB,
        content="你记得我的开发习惯吗？",
    ))
    metrics = agent.last_action_trace["runtime_metrics"]
    assert metrics["memory_hits"] == 1
    assert metrics["memory_candidates"][0]["id"] == "memory-actual"
    assert metrics["memory_candidates"][0]["semantic_score"] == 0.64


async def test_agent_interim_is_not_persisted_as_assistant_message():
    provider = FakeProvider([
        ModelResponse(tool_calls=[ToolCall(id="catalog", name="inspect_tool_catalog",
                                           arguments={"action": "summary"})]),
        ModelResponse(tool_calls=[ToolCall(id="interim", name="emit_interim_reply",
                                           arguments={"content": "我先把这几条记录对一下～"})]),
        ModelResponse(content="核对结果已整理。"),
    ])
    agent = ZhaoxiAgent(provider=provider, registry=ToolRegistry(),
                        context_builder=ContextBuilder("你是朝汐。"))
    agent.settings = Settings(interim_reply_threshold_seconds=0)
    gateway = InterfaceGateway(agent)
    events = []
    gateway.event_sink = events.append
    result = await gateway.chat(UnifiedMessage(
        request_id="interim-test", channel=InterfaceChannel.WEB, content="帮我核对几条记录"))
    assert result.content == "核对结果已整理。"
    assert any(event["type"] == "interim_reply" for event in events)
    assert [item.content for item in agent.conversation.messages if item.role.value == "assistant"] == ["核对结果已整理。"]
    assert gateway.agent.last_action_trace["runtime_metrics"]["interim_replies"] == 1


def test_planner_trace_bridges_into_action_trace():
    events = []
    with correlation_scope(CorrelationContext(trace_id="trace", request_id="request")):
        with action_trace_scope(events.append) as trace:
            goal = Goal(description="检查记录")
            recorder = TraceRecorder()
            recorder.record(goal, "goal_created")
            recorder.record(goal, "plan_created", metadata={"step_count": 2})
            recorder.record(goal, "task_completed")
            assert trace.planner_used
    types = [event["event"]["event_type"] for event in events]
    assert types == ["planner_started", "planner_plan_created", "planner_finished"]


async def test_llm_metrics_record_owner_usage_and_duration():
    provider = ResilientProvider([FakeProvider([
        ModelResponse(content="完成", usage={"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
                      finish_reason="stop")])])
    with correlation_scope(CorrelationContext(trace_id="trace", request_id="request")):
        with action_trace_scope(lambda event: None) as trace:
            with provider_budget_scope(12, 100_000):
                await provider.generate([])
            trace.finish()
    call = trace.metrics()["llm_calls"][0]
    assert call["owner"] == "agent"
    assert call["prompt_tokens"] == 12
    assert call["output_tokens"] == 5
    assert call["total_tokens"] == 17
    assert call["duration_ms"] >= 0


async def test_interim_then_provider_failure_has_terminal_trace_and_no_history_pollution():
    class FailingProvider(FakeProvider):
        async def generate(self, messages, tools=None, **kwargs):
            if len(self.calls) >= 2:
                raise ProviderError("upstream unavailable", code="provider_transport_error")
            return await super().generate(messages, tools, **kwargs)

    provider = FailingProvider([
        ModelResponse(tool_calls=[ToolCall(id="catalog", name="inspect_tool_catalog",
                                           arguments={"action": "summary"})]),
        ModelResponse(tool_calls=[ToolCall(id="interim", name="emit_interim_reply",
                                           arguments={"content": "我先把这些线索对一下～"})]),
    ])
    agent = ZhaoxiAgent(provider=provider, registry=ToolRegistry(),
                        context_builder=ContextBuilder("你是朝汐。"))
    agent.settings = Settings(interim_reply_threshold_seconds=0)
    gateway = InterfaceGateway(agent)
    events = []
    gateway.event_sink = events.append
    with pytest.raises(AgentLoopError):
        await gateway.chat(UnifiedMessage(request_id="failed-interim",
                           channel=InterfaceChannel.WEB, content="帮我查一下线索"))
    assert any(event["type"] == "interim_reply" for event in events)
    assert agent.last_action_trace["response_status"] == "failed"
    assert agent.last_action_trace["runtime_metrics"]["finished_at"]
    assert all("我先把这些线索对一下" not in (item.content or "")
               for item in agent.conversation.messages)


async def test_slow_model_does_not_emit_timer_based_interim():
    import asyncio
    class SlowProvider(FakeProvider):
        async def generate(self, messages, tools=None, **kwargs):
            await asyncio.sleep(0.04)
            return await super().generate(messages, tools, **kwargs)
    agent = ZhaoxiAgent(provider=SlowProvider([ModelResponse(content="处理好了。")]),
                        registry=ToolRegistry(), context_builder=ContextBuilder("你是朝汐。"))
    agent.settings = Settings(interim_reply_threshold_seconds=0.01)
    gateway = InterfaceGateway(agent)
    events = []
    gateway.event_sink = events.append
    await gateway.chat(UnifiedMessage(request_id="slow", channel=InterfaceChannel.WEB, content="你好"))
    interim = [event for event in events if event["type"] == "interim_reply"]
    assert interim == []
    final = next(event["event"] for event in events if event.get("event", {}).get("event_type") == "runtime_metrics_finalized")
    assert final["metadata"]["runtime_metrics"]["total_ms"] > 0
    assert "timeline" not in final["metadata"]["runtime_metrics"]


def test_planner_steps_include_description_status_and_duration():
    from zhaoxi.planner.models import Plan, PlanStep
    goal = Goal(description="核对记录")
    step = PlanStep(description="读取饮食记录")
    goal.plans.append(Plan(goal_id=goal.id, revision=1, steps=[step]))
    with correlation_scope(CorrelationContext(trace_id="p", request_id="p")), action_trace_scope() as trace:
        recorder = TraceRecorder()
        recorder.record(goal, "plan_created")
        recorder.record(goal, "step_started", step_id=step.id)
        recorder.record(goal, "step_completed", step_id=step.id)
        assert trace.events[0].metadata["steps"][0]["description"] == "读取饮食记录"
        assert "读取饮食记录" in trace.events[-1].display_message
        assert trace.events[-1].metadata["duration_ms"] >= 0

def test_current_cognition_observatory_counters():
    trace = ActionTrace("trace", "request")
    trace.emit("current_cognition_gate", "current_cognition", "success", "gate",
               metadata={"triggered": True, "reason": "state_signal"})
    trace.emit("current_cognition_triggered", "current_cognition", "success", "trigger")
    trace.emit("current_cognition_applied", "current_cognition", "success", "applied",
               metadata={"duration_ms": 12.5, "ops_count": 2, "threads_added": 1,
                         "threads_updated": 0, "threads_removed": 0})
    metrics = trace.metrics()
    assert metrics["current_cognition_gate"]["triggered"] is True
    assert metrics["current_cognition_triggered"] == 1
    assert metrics["current_cognition_model_ms"] == 12.5
    assert metrics["current_cognition_ops_count"] == 2
    assert metrics["threads_added"] == 1
