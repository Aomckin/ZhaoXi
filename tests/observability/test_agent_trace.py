"""End-to-end accounting through the real gateway and agent tool loop."""

import asyncio
import logging

import pytest
from pydantic import BaseModel

from conftest import FakeProvider
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.errors import AgentLoopError, ProviderError
from zhaoxi.interfaces.gateway import InterfaceGateway
from zhaoxi.interfaces.models import InterfaceChannel, UnifiedMessage
from zhaoxi.models.types import ModelResponse, ToolCall
from zhaoxi.observability import action_trace_scope
from zhaoxi.permission.models import InvocationOrigin, PermissionLevel, SideEffect
from zhaoxi.permission.executor import ToolExecutor
from zhaoxi.proactive.heartbeat import TidalHeartbeat
from zhaoxi.reliability import CorrelationContext, correlation_scope
from zhaoxi.reliability.metrics import MetricRegistry
from zhaoxi.reliability.retry import provider_budget_scope, record_provider_tokens
from zhaoxi.tools.base import Tool, ToolResult
from zhaoxi.tools.registry import ToolRegistry


class AddInput(BaseModel):
    label: str


class AddTool(Tool):
    name = "agenda_add"
    description = "添加日程"
    input_model = AddInput
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.LOCAL_STATE})
    default_confirm_write = False

    def __init__(self):
        self.calls = 0
        self.fail = False

    async def execute(self, arguments: AddInput) -> ToolResult:
        self.calls += 1
        if self.fail:
            return ToolResult(success=False, content="失败", error="write_failed")
        return ToolResult(success=True, content="已添加", data={"created": True, "item": {"id": f"item-{self.calls}"}})


def setup_gateway(responses, tool=None):
    registry = ToolRegistry()
    if tool:
        registry.register(tool)
    agent = ZhaoxiAgent(provider=FakeProvider(responses), registry=registry,
                        context_builder=ContextBuilder("你是朝汐。"))
    gateway = InterfaceGateway(agent)
    emitted = []
    gateway.event_sink = emitted.append
    return agent, gateway, emitted


async def send(gateway, request_id="trace-1"):
    return await gateway.chat(UnifiedMessage(request_id=request_id,
                              channel=InterfaceChannel.WEB, content="添加日程"))


def call(call_id, label=None):
    return ToolCall(id=call_id, name="agenda_add",
                    arguments={"label": label} if label is not None else {})


async def test_one_tool_success_has_correlated_events_and_record_id():
    tool = AddTool()
    agent, gateway, emitted = setup_gateway([
        ModelResponse(tool_calls=[call("first", "面试")]), ModelResponse(content="已办好。")], tool)
    result = await send(gateway)
    trace = agent.last_action_trace
    assert result.content == "已办好。"
    assert trace["task_status"] == "completed" and trace["response_status"] == "succeeded"
    assert trace["actions"][0]["invocation_id"]
    assert trace["actions"][0]["record_id"] != "item-1"
    events = [item["event"] for item in emitted]
    assert all(item["trace_id"] == "trace-1" and item["request_id"] == "trace-1" for item in events)
    assert {"tool_call_started", "tool_call_succeeded", "task_completed"} <= {item["event_type"] for item in events}
    assert all("面试" not in str(item) for item in events)


async def test_validation_retry_supersedes_only_the_failed_attempt():
    tool = AddTool()
    agent, gateway, emitted = setup_gateway([
        ModelResponse(tool_calls=[call("bad")]),
        ModelResponse(tool_calls=[call("fixed", "面试")]),
        ModelResponse(content="已办好。")], tool)
    await send(gateway)
    actions = agent.last_action_trace["actions"]
    assert [item["status"] for item in actions] == ["superseded", "completed"]
    assert actions[0]["superseded_by"] == actions[1]["invocation_id"]
    assert agent.last_action_trace["task_status"] == "completed"
    failed = next(item["event"] for item in emitted if item["event"]["event_type"] == "tool_validation_failed")
    assert failed["metadata"]["supplied_keys"] == []
    assert failed["metadata"]["schema_hash"]


async def test_two_same_name_writes_keep_distinct_invocations():
    tool = AddTool()
    agent, gateway, _ = setup_gateway([
        ModelResponse(tool_calls=[call("a", "甲"), call("b", "乙")]),
        ModelResponse(content="两项已添加。")], tool)
    await send(gateway)
    actions = agent.last_action_trace["actions"]
    assert tool.calls == 2
    assert [item["status"] for item in actions] == ["completed", "completed"]
    assert len({item["invocation_id"] for item in actions}) == 2
    assert len({item["record_id"] for item in actions}) == 2


async def test_same_step_calls_do_not_misidentify_a_separate_write_as_retry():
    tool = AddTool()
    agent, gateway, _ = setup_gateway([
        ModelResponse(tool_calls=[call("bad"), call("other", "乙")]),
        ModelResponse(content="第二项已添加。")], tool)
    await send(gateway)
    assert [item["status"] for item in agent.last_action_trace["actions"]] == ["failed", "completed"]
    assert agent.last_action_trace["task_status"] == "partial"


async def test_budget_failure_after_write_preserves_completed_task():
    class BudgetProvider(FakeProvider):
        async def generate(self, messages, tools=None, **kwargs):
            if self.calls:
                raise ProviderError("预算耗尽", code="provider_token_budget_exhausted")
            return await super().generate(messages, tools, **kwargs)

    tool = AddTool()
    agent, gateway, emitted = setup_gateway([], tool)
    agent.provider = BudgetProvider([ModelResponse(tool_calls=[call("a", "甲")])])
    result = await send(gateway)
    assert "Token" in result.content
    assert agent.last_action_trace["task_status"] == "completed"
    assert agent.last_action_trace["response_status"] == "failed"
    assert any(item["event"]["error_code"] == "token_budget_exhausted" for item in emitted)
    terminal = [item["event"] for item in emitted if item["event"]["event_type"] == "task_completed"][-1]
    assert terminal["display_message"] == "已完成的操作均已保留"
    assert terminal["metadata"]["response_status"] == "failed"


async def test_provider_http_error_is_not_tool_error():
    class HttpProvider(FakeProvider):
        async def generate(self, messages, tools=None, **kwargs):
            raise ProviderError("HTTP 503", code="provider_http_503")

    agent, gateway, emitted = setup_gateway([])
    agent.provider = HttpProvider([])
    with pytest.raises(AgentLoopError) as error:
        await send(gateway)
    assert error.value.code == "provider_http_error"
    assert agent.last_action_trace["task_status"] == "failed"
    assert not agent.last_action_trace["actions"]
    assert any(item["event"]["error_code"] == "provider_http_error" for item in emitted)


async def test_final_tool_failure_is_not_repaired_by_a_failed_retry():
    tool = AddTool()
    tool.fail = True
    agent, gateway, _ = setup_gateway([
        ModelResponse(tool_calls=[call("bad")]),
        ModelResponse(tool_calls=[call("failed", "面试")]),
        ModelResponse(content="没办成。")], tool)
    await send(gateway)
    assert [item["status"] for item in agent.last_action_trace["actions"]] == ["superseded", "failed"]
    assert agent.last_action_trace["task_status"] == "failed"
    with correlation_scope(CorrelationContext(trace_id="recovery", request_id="recovery")), action_trace_scope() as trace:
        trace.actions = []
        from zhaoxi.observability import ActionAttempt
        trace.actions.append(ActionAttempt("agenda_add", "a", "a", 1, status="failed"))
        assert "仍失败：agenda_add" in agent._recoverable_turn_content("回复失败")


async def test_write_exception_has_unknown_outcome():
    class UncertainTool(AddTool):
        async def execute(self, arguments):
            raise RuntimeError("possibly after write")

    agent, gateway, _ = setup_gateway([
        ModelResponse(tool_calls=[call("uncertain", "甲")]),
        ModelResponse(content="无法确认。")], UncertainTool())
    await send(gateway)
    assert agent.last_action_trace["actions"][0]["status"] == "unknown"
    assert agent.last_action_trace["task_status"] == "failed"


def test_budget_event_contains_numerical_context():
    events = []
    with correlation_scope(CorrelationContext(trace_id="budget", request_id="budget")), action_trace_scope(events.append):
        with provider_budget_scope(2, 10):
            record_provider_tokens(6, input_tokens=4, output_tokens=2, provider="fake", model="m")
            with pytest.raises(ProviderError):
                record_provider_tokens(5, input_tokens=3, output_tokens=2, provider="fake", model="m")
    exhausted = next(item["event"] for item in events if item["event"]["event_type"] == "token_budget_exhausted")
    assert exhausted["metadata"] == {"used_before": 6, "call_input_tokens": 3,
                                     "call_output_tokens": 2, "call_total": 5,
                                     "used_after": 11, "limit": 10, "step": None,
                                     "provider": "fake", "model": "m"}


async def test_validation_diagnostics_redact_unknown_argument_keys():
    registry = ToolRegistry()
    registry.register(AddTool())
    execution = await ToolExecutor(registry).execute(
        "agenda_add", {"secret-token-as-a-key": "private value"},
        request_id="safe", origin=InvocationOrigin.AGENT,
    )
    assert execution.failure_kind == "validation"
    assert "secret-token-as-a-key" not in str(execution.safe_metadata)
    assert "private value" not in str(execution.safe_metadata)
    assert execution.safe_metadata["supplied_keys"][0].startswith("unknown:")


async def test_heartbeat_top_level_failure_is_logged(monkeypatch, caplog):
    heartbeat = object.__new__(TidalHeartbeat)
    heartbeat.metrics = MetricRegistry()
    heartbeat.updated = asyncio.Event()
    heartbeat.settings = type("Settings", (), {"proactive_heartbeat_seconds": 1})()

    async def fail():
        raise RuntimeError("private detail")

    async def stop(_):
        raise asyncio.CancelledError

    heartbeat.tick = fail
    monkeypatch.setattr("zhaoxi.proactive.heartbeat.asyncio.sleep", stop)
    with caplog.at_level(logging.ERROR), pytest.raises(asyncio.CancelledError):
        await heartbeat.run()
    assert any("error_code=heartbeat_error error_type=RuntimeError" in record.message for record in caplog.records)
    assert all("private detail" not in record.message for record in caplog.records)
