"""Overall result must reflect reply failure while retaining completed tool effects."""
import pytest

from conftest import FakeProvider
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.errors import AgentLoopError, ProviderError
from zhaoxi.interfaces.gateway import InterfaceGateway
from zhaoxi.interfaces.models import InterfaceChannel, UnifiedMessage
from zhaoxi.models.types import ModelResponse
from zhaoxi.observability import ActionTrace
from zhaoxi.tools.registry import ToolRegistry


@pytest.mark.parametrize("actions,reply,result,terminal,expected,task", [
    ([], "succeeded", "completed", None, "completed", "completed"),
    ([], "failed", "completed", None, "failed", "failed"),
    ([True], "failed", "completed", None, "failed", "completed"),
    ([True, False], "failed", "completed", None, "failed", "partial"),
    ([True, False], "succeeded", "completed", None, "partial_success", "partial"),
    ([False], "succeeded", "completed", None, "failed", "failed"),
    ([], "waiting_for_permission", "completed", "waiting_for_permission", "waiting_for_permission", "waiting_for_permission"),
    ([True], "succeeded", "budget_exhausted", None, "budget_exhausted", "completed"),
    ([], "succeeded", "budget_exhausted", None, "budget_exhausted", "failed"),
])
def test_overall_status_matches_progress_and_reply(actions, reply, result, terminal, expected, task):
    emitted = []
    trace = ActionTrace("trace", "request", emitted.append)
    for i, success in enumerate(actions):
        attempt = trace.start_tool("agenda_add", str(i), "inv-" + str(i), i)
        trace.finish_tool(attempt, success=success, record_id="saved-record" if success else None)
    trace.response_status, trace.result_status, trace.terminal_status = reply, result, terminal
    before = trace.metrics()
    assert before["result_status"] == expected
    trace.finish()
    assert trace.result_status == expected and trace.task_status == task
    metrics = trace.metrics()
    assert metrics["result_status"] == expected
    assert metrics["task_status"] == task and metrics["response_status"] == reply
    assert metrics["partial_success"] == (expected == "partial_success")
    assert emitted[-1]["event"]["metadata"]["runtime_metrics"]["result_status"] == expected
    assert all(action.record_id == "saved-record" for action in trace.actions if action.status == "completed")
    trace.finish()
    assert sum(e["event"]["event_type"] == "runtime_metrics_finalized" for e in emitted) == 1


def test_runtime_failure_overrides_success_default_without_losing_tool_record():
    trace = ActionTrace("trace", "request")
    attempt = trace.start_tool("agenda_add", "1", "inv-1", 1)
    trace.finish_tool(attempt, success=True, record_id="saved")
    trace.response_status = "succeeded"
    trace.emit("runtime_finished", "runtime", "failed", "运行未完成")
    trace.finish()
    assert trace.result_status == "failed"
    assert trace.task_status == "completed" and trace.actions[0].record_id == "saved"


def test_metrics_disabled_still_finalizes_correct_result():
    trace = ActionTrace("trace", "request", metrics_enabled=False)
    trace.response_status = "failed"
    trace.finish()
    assert trace.result_status == "failed" and trace.task_status == "failed"
    assert trace.metrics() == {"enabled": False, "request_id": "request", "trace_id": "trace"}


class FailingProvider(FakeProvider):
    async def generate(self, messages, tools=None, **kwargs):
        raise ProviderError("upstream failed", code="provider_transport_error", retryable=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("regenerate", [False, True])
async def test_gateway_endpoint_failure_exports_failed_metrics(regenerate):
    agent = ZhaoxiAgent(provider=FakeProvider([ModelResponse(content="原回复")]),
                        registry=ToolRegistry(), context_builder=ContextBuilder("朝汐"))
    gateway = InterfaceGateway(agent)
    events = []
    gateway.event_sink = events.append
    if regenerate:
        original = await gateway.chat(UnifiedMessage(request_id="seed", channel=InterfaceChannel.WEB, content="你好"))
    agent.provider = FailingProvider([])
    with pytest.raises(AgentLoopError):
        if regenerate:
            await gateway.regenerate(original.message_id, request_id="failed")
        else:
            await gateway.chat(UnifiedMessage(request_id="failed", channel=InterfaceChannel.WEB, content="你好"))
    summary = agent.last_action_trace
    assert summary["response_status"] == "failed" and summary["task_status"] == "failed"
    assert summary["runtime_metrics"]["result_status"] == "failed"
    finalized = [e["event"] for e in events if e.get("type") == "agent_event" and e["event"]["event_type"] == "runtime_metrics_finalized" and e["event"]["request_id"] == "failed"]
    assert len(finalized) == 1 and finalized[0]["metadata"]["runtime_metrics"]["result_status"] == "failed"
