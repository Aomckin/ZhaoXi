from pydantic import BaseModel

from conftest import FakeProvider
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.core.message import Role
from zhaoxi.models.types import ModelResponse, ToolCall
from zhaoxi.permission.audit import InMemoryAuditSink
from zhaoxi.permission.executor import ToolExecutor
from zhaoxi.permission.gateway import PermissionGateway
from zhaoxi.permission.models import InvocationOrigin, PermissionLevel, SideEffect
from zhaoxi.planner.models import GoalStatus
from zhaoxi.planner.runtime import PlannerRuntime
from zhaoxi.tools.base import Tool, ToolResult
from zhaoxi.tools.registry import ToolRegistry


class WriteInput(BaseModel):
    value: str


class WriteTool(Tool):
    name = "write_value"
    description = "写入一个测试值。"
    input_model = WriteInput
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.LOCAL_STATE})

    def __init__(self):
        self.values = []

    async def execute(self, arguments):
        self.values.append(arguments.value)
        return ToolResult(success=True, content="已写入。")


class OtherWriteTool(WriteTool):
    name = "write_other"
    description = "写入另一类测试值。"


def permission_runtime():
    registry = ToolRegistry()
    tool = WriteTool()
    registry.register(tool)
    audit = InMemoryAuditSink()
    gateway = PermissionGateway(audit=audit)
    return registry, tool, audit, ToolExecutor(registry, gateway)


async def test_write_waits_for_confirmation_and_executes_exactly_once():
    _, tool, audit, executor = permission_runtime()
    waiting = await executor.execute(
        "write_value",
        {"value": "safe"},
        request_id="r1",
        origin=InvocationOrigin.AGENT,
        user_intent="保存这个值",
    )
    assert waiting.waiting_for_permission
    assert tool.values == []

    executor.gateway.approve(waiting.confirmation.confirmation_id)
    completed = await executor.execute(
        "write_value",
        {"value": "safe"},
        request_id="r1",
        origin=InvocationOrigin.AGENT,
        user_intent="保存这个值",
        invocation_id=waiting.request.invocation_id,
    )
    assert completed.result.success
    assert tool.values == ["safe"]
    assert completed.result.metadata["trust"] == "untrusted_tool_output"
    assert [event.event_type for event in audit.events][-2:] == [
        "tool_execution_started",
        "tool_execution_succeeded",
    ]


async def test_changed_arguments_cannot_reuse_grant():
    _, tool, _, executor = permission_runtime()
    waiting = await executor.execute(
        "write_value", {"value": "safe"}, request_id="r", origin=InvocationOrigin.AGENT
    )
    executor.gateway.approve(waiting.confirmation.confirmation_id)
    changed = await executor.execute(
        "write_value",
        {"value": "changed"},
        request_id="r",
        origin=InvocationOrigin.AGENT,
        invocation_id=waiting.request.invocation_id,
    )
    assert changed.waiting_for_permission
    assert tool.values == []


async def test_read_only_intent_denies_write_without_confirmation():
    _, tool, audit, executor = permission_runtime()
    execution = await executor.execute(
        "write_value",
        {"value": "x"},
        request_id="r",
        origin=InvocationOrigin.PLANNER,
        user_intent="只读检查，不要修改",
    )
    assert execution.result.error == "read_only_intent"
    assert not execution.waiting_for_permission
    assert tool.values == []
    assert audit.events[-1].event_type == "permission_denied"


async def test_agent_approval_resumes_original_call():
    registry, tool, _, executor = permission_runtime()
    provider = FakeProvider([
        ModelResponse(tool_calls=[ToolCall(id="call-1", name="write_value", arguments={"value": "one"})]),
        ModelResponse(content="完成。"),
    ])
    agent = ZhaoxiAgent(
        provider=provider,
        registry=registry,
        context_builder=ContextBuilder("你是朝汐。"),
        conversation=Conversation(),
        tool_executor=executor,
    )
    waiting = await agent.run("保存一个值")
    assert waiting.permission_confirmation
    assert tool.values == []
    completed = await agent.approve_permission(waiting.permission_confirmation.confirmation_id)
    assert completed.content == "完成。"
    assert tool.values == ["one"]


async def test_natural_language_approval_resolves_pending_before_llm():
    registry, tool, _, executor = permission_runtime()
    provider = FakeProvider([
        ModelResponse(tool_calls=[
            ToolCall(id="pending-approve", name="write_value", arguments={"value": "approved"})
        ]),
        ModelResponse(content="批准后完成。"),
    ])
    conversation = Conversation()
    agent = ZhaoxiAgent(
        provider=provider,
        registry=registry,
        context_builder=ContextBuilder("你是朝汐。"),
        conversation=conversation,
        tool_executor=executor,
    )

    waiting = await agent.run_natural("保存这个值")
    assert waiting.permission_confirmation
    assert len(provider.calls) == 1

    completed = await agent.run_natural("允许")
    assert completed.content == "批准后完成。"
    assert tool.values == ["approved"]
    assert len(provider.calls) == 2
    assert [message.role for message in provider.calls[1][-2:]] == [Role.ASSISTANT, Role.TOOL]
    assert provider.calls[1][-1].tool_call_id == "pending-approve"
    assert not any(message.role == Role.USER and message.content == "允许" for message in conversation.messages)


async def test_natural_language_denial_writes_tool_result_and_resumes_loop():
    registry, tool, _, executor = permission_runtime()
    provider = FakeProvider([
        ModelResponse(tool_calls=[
            ToolCall(id="pending-deny", name="write_value", arguments={"value": "denied"})
        ]),
        ModelResponse(content="已取消写入。"),
    ])
    conversation = Conversation()
    agent = ZhaoxiAgent(
        provider=provider,
        registry=registry,
        context_builder=ContextBuilder("你是朝汐。"),
        conversation=conversation,
        tool_executor=executor,
    )

    waiting = await agent.run_natural("尝试保存")
    assert waiting.permission_confirmation
    completed = await agent.run_natural("拒绝")
    assert completed.content == "已取消写入。"
    assert tool.values == []
    assert len(provider.calls) == 2
    tool_message = provider.calls[1][-1]
    assert tool_message.role == Role.TOOL
    assert tool_message.tool_call_id == "pending-deny"
    assert "permission_denied" in tool_message.content
    assert not any(message.role == Role.USER and message.content == "拒绝" for message in conversation.messages)


async def test_unrecognized_pending_reply_never_reaches_llm_or_creates_orphan():
    registry, _, _, executor = permission_runtime()
    provider = FakeProvider([
        ModelResponse(tool_calls=[
            ToolCall(id="pending-unknown", name="write_value", arguments={"value": "x"})
        ])
    ])
    conversation = Conversation()
    agent = ZhaoxiAgent(
        provider=provider,
        registry=registry,
        context_builder=ContextBuilder("你是朝汐。"),
        conversation=conversation,
        tool_executor=executor,
    )
    await agent.run_natural("尝试保存")
    response = await agent.run_natural("我再想想")
    assert "等待确认" in response.content
    assert len(provider.calls) == 1
    assert not any(message.role == Role.USER and message.content == "我再想想" for message in conversation.messages)


async def test_agent_merges_consecutive_same_tool_permissions():
    registry, tool, _, executor = permission_runtime()
    provider = FakeProvider([
        ModelResponse(tool_calls=[
            ToolCall(id="call-1", name="write_value", arguments={"value": "one"}),
            ToolCall(id="call-2", name="write_value", arguments={"value": "two"}),
        ]),
        ModelResponse(content="全部完成。"),
    ])
    agent = ZhaoxiAgent(
        provider=provider,
        registry=registry,
        context_builder=ContextBuilder("你是朝汐。"),
        conversation=Conversation(),
        tool_executor=executor,
    )
    first = await agent.run("保存两个值")
    assert "批量执行 2 项" in first.content
    completed = await agent.approve_permission(first.permission_confirmation.confirmation_id)
    assert completed.content == "全部完成。"
    assert tool.values == ["one", "two"]


async def test_agent_does_not_merge_different_tools():
    registry, tool, _, executor = permission_runtime()
    other = OtherWriteTool()
    registry.register(other)
    provider = FakeProvider([
        ModelResponse(tool_calls=[
            ToolCall(id="call-1", name="write_value", arguments={"value": "one"}),
            ToolCall(id="call-2", name="write_other", arguments={"value": "two"}),
        ]),
        ModelResponse(content="全部完成。"),
    ])
    agent = ZhaoxiAgent(
        provider=provider,
        registry=registry,
        context_builder=ContextBuilder("你是朝汐。"),
        conversation=Conversation(),
        tool_executor=executor,
    )
    first = await agent.run("保存两类值")
    second = await agent.approve_permission(first.permission_confirmation.confirmation_id)
    assert second.permission_confirmation
    assert tool.values == ["one"]
    assert other.values == []
    completed = await agent.approve_permission(second.permission_confirmation.confirmation_id)
    assert completed.content == "全部完成。"
    assert other.values == ["two"]


async def test_agent_batch_denial_fills_every_tool_result_without_execution():
    registry, tool, _, executor = permission_runtime()
    provider = FakeProvider([
        ModelResponse(tool_calls=[
            ToolCall(id="deny-1", name="write_value", arguments={"value": "one"}),
            ToolCall(id="deny-2", name="write_value", arguments={"value": "two"}),
        ]),
        ModelResponse(content="整批已取消。"),
    ])
    conversation = Conversation()
    agent = ZhaoxiAgent(
        provider=provider,
        registry=registry,
        context_builder=ContextBuilder("你是朝汐。"),
        conversation=conversation,
        tool_executor=executor,
    )
    waiting = await agent.run_natural("保存两个值")
    completed = await agent.run_natural("拒绝")
    assert completed.content == "整批已取消。"
    assert tool.values == []
    tool_messages = [item for item in provider.calls[1] if item.role == Role.TOOL]
    assert [item.tool_call_id for item in tool_messages[-2:]] == ["deny-1", "deny-2"]


async def test_agent_batch_supports_partial_natural_language_selection():
    registry, tool, _, executor = permission_runtime()
    calls = [
        ToolCall(id=f"partial-{index}", name="write_value", arguments={"value": str(index)})
        for index in range(1, 5)
    ]
    provider = FakeProvider([
        ModelResponse(tool_calls=calls),
        ModelResponse(content="已按选择处理。"),
    ])
    conversation = Conversation()
    agent = ZhaoxiAgent(
        provider=provider,
        registry=registry,
        context_builder=ContextBuilder("你是朝汐。"),
        conversation=conversation,
        tool_executor=executor,
    )
    waiting = await agent.run_natural("处理四项")
    assert "批量执行 4 项" in waiting.content

    completed = await agent.run_natural("只删12，保留34")
    assert completed.content == "已按选择处理。"
    assert tool.values == ["1", "2"]
    tool_messages = [item for item in provider.calls[1] if item.role == Role.TOOL]
    assert [item.tool_call_id for item in tool_messages[-4:]] == [
        "partial-1", "partial-2", "partial-3", "partial-4"
    ]
    assert "permission_denied" in tool_messages[-2].content
    assert "permission_denied" in tool_messages[-1].content


def test_partial_selection_parser_is_conservative_for_large_batches():
    assert ZhaoxiAgent._permission_selection("只删12，保留34", 4) == {1, 2}
    assert ZhaoxiAgent._permission_selection("只删12", 20) == {12}
    assert ZhaoxiAgent._permission_selection("只删99", 4) is None


def planner_call(name, arguments):
    return ModelResponse(tool_calls=[ToolCall(id=name, name=name, arguments=arguments)])


async def test_planner_waits_and_resumes_same_goal():
    registry, tool, _, executor = permission_runtime()
    planner = PlannerRuntime(
        provider=FakeProvider([
            planner_call("create_plan", {"steps": ["写入"]}),
            planner_call("write_value", {"value": "planned"}),
            planner_call("finish_task", {"summary": "完成。"}),
        ]),
        registry=registry,
        context_builder=ContextBuilder("你是朝汐。"),
        tool_executor=executor,
    )
    waiting = await planner.run("保存计划值")
    assert waiting.status == GoalStatus.WAITING_FOR_PERMISSION
    assert tool.values == []
    completed = await planner.approve_permission(waiting.permission_confirmation.confirmation_id)
    assert completed.goal_id == waiting.goal_id
    assert completed.status == GoalStatus.COMPLETED
    assert tool.values == ["planned"]


async def test_cancelling_planner_invalidates_pending_confirmation():
    registry, tool, _, executor = permission_runtime()
    planner = PlannerRuntime(
        provider=FakeProvider([
            planner_call("create_plan", {"steps": ["写入"]}),
            planner_call("write_value", {"value": "never"}),
        ]),
        registry=registry,
        context_builder=ContextBuilder("你是朝汐。"),
        tool_executor=executor,
    )
    waiting = await planner.run("保存后等待")
    confirmation_id = waiting.permission_confirmation.confirmation_id
    await planner.cancel(waiting.goal_id)
    confirmation = executor.gateway.store.pending[confirmation_id]
    assert confirmation.resolved and confirmation.approved is False
    assert tool.values == []
