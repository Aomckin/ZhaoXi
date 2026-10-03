"""Recommendation does not grant execution authority."""
from pydantic import BaseModel

from zhaoxi.decision.action_guard import guard_action
from zhaoxi.permission.executor import ToolExecutor
from zhaoxi.permission.models import InvocationOrigin, PermissionLevel, SideEffect
from zhaoxi.tools.base import Tool, ToolResult
from zhaoxi.tools.registry import ToolRegistry


class Empty(BaseModel):
    pass


class ExternalWrite(Tool):
    name = "external_test_write"
    description = "测试外部写入"
    input_model = Empty
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.EXTERNAL_SERVICE_WRITE})
    calls = 0
    high_impact = True

    async def execute(self, arguments):
        self.calls += 1
        return ToolResult(success=True, content="done")


def test_pick_and_read_context_have_no_execution_guard():
    assert not guard_action(PermissionLevel.READ, frozenset({SideEffect.NONE})).requires_confirmation


async def test_external_write_cannot_bypass_guard_by_pick_or_disabled_write_prompt():
    registry = ToolRegistry()
    tool = registry.register(ExternalWrite())
    registry.update_tools(name=tool.name, confirm_write=False)
    executor = ToolExecutor(registry)
    args = {"request_id":"test", "origin":InvocationOrigin.AGENT, "user_intent":"你直接替我决定并付款"}
    result = await executor.execute(tool.name, {}, invocation_id="one", **args)
    assert result.waiting_for_permission and tool.calls == 0
    assert result.safe_metadata["decision_guard_flags"] == ["external_action", "high_impact_action"]
    executor.gateway.approve(result.confirmation.confirmation_id)
    approved = await executor.execute(tool.name, {}, invocation_id="one", **args)
    assert approved.result.success and tool.calls == 1
    again = await executor.execute(tool.name, {}, invocation_id="two", **args)
    assert again.waiting_for_permission and tool.calls == 1


def test_irreversible_and_high_impact_actions_always_have_boundaries():
    assert guard_action(PermissionLevel.DELETE, frozenset({SideEffect.DATA_DELETION})).requires_confirmation
    assert guard_action(PermissionLevel.WRITE, frozenset({SideEffect.LOCAL_STATE}), high_impact=True).requires_confirmation
    assert guard_action(PermissionLevel.DANGEROUS, frozenset({SideEffect.SYSTEM_CHANGE})).requires_confirmation
