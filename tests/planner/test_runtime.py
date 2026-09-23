import pytest
from pydantic import BaseModel

from conftest import FakeProvider
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.models.types import ModelResponse, ToolCall
from zhaoxi.planner.models import Goal, GoalStatus, Plan, PlanStep, StepStatus
from zhaoxi.planner.runtime import PlannerRuntime
from zhaoxi.models.resilient import ResilientProvider
from zhaoxi.reliability.retry import BudgetPolicy, provider_budget_scope, record_provider_tokens
from zhaoxi.tools.base import Tool, ToolResult
from zhaoxi.tools.builtin import create_builtin_tools
from zhaoxi.tools.registry import ToolRegistry


def call(name, arguments, call_id=None):
    return ModelResponse(tool_calls=[
        ToolCall(id=call_id or name, name=name, arguments=arguments)
    ])


def make_planner(responses, registry=None, **kwargs):
    value = registry or ToolRegistry()
    if registry is None:
        for tool in create_builtin_tools():
            value.register(tool)
    return PlannerRuntime(
        provider=FakeProvider(responses),
        registry=value,
        context_builder=ContextBuilder("你是朝汐。"),
        conversation=Conversation(),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_complex_plan_requests_one_extension_and_final_reply_omits_tool_schemas():
    policy = BudgetPolicy(1000, 400, 200, 1600, 200)
    responses = [
        call("create_plan", {"steps": ["计算", "复述"]}),
        call("calculator", {"expression": "17*23"}),
        call("echo", {"message": "完成"}),
        ModelResponse(content="结果是 391，且已完成复述。"),
    ]
    for response, amount in zip(responses, (450, 400, 500, 100)):
        response.usage = {"prompt_tokens": amount - 10, "completion_tokens": 10,
                          "total_tokens": amount}
    fake = FakeProvider(responses)
    planner = make_planner([], max_steps=6)
    planner.provider = ResilientProvider([fake], max_total_tokens=1000, budget_policy=policy)
    with provider_budget_scope(8, policy=policy) as budget:
        result = await planner.run("计算后复述")
    assert result.status == GoalStatus.COMPLETED
    assert budget.extension_count == 1
    assert fake.tool_schemas[-1] is None


@pytest.mark.asyncio
async def test_completed_single_tool_uses_reserve_without_extension():
    policy = BudgetPolicy(1000, 400, 200, 1600, 200)
    responses = [call("create_plan", {"steps": ["计算"]}),
                 call("calculator", {"expression": "2+3"}),
                 ModelResponse(content="结果是 5。")]
    for response, amount in zip(responses, (450, 400, 120)):
        response.usage = {"prompt_tokens": amount - 10, "completion_tokens": 10,
                          "total_tokens": amount}
    fake = FakeProvider(responses)
    planner = make_planner([], max_steps=5)
    planner.provider = ResilientProvider([fake], max_total_tokens=1000, budget_policy=policy)
    with provider_budget_scope(8, policy=policy) as budget:
        result = await planner.run("计算 2+3")
    assert result.status == GoalStatus.COMPLETED
    assert budget.extension_count == 0
    assert budget.reserve_entered is True
    assert fake.tool_schemas[-1] is None


@pytest.mark.asyncio
async def test_planner_structured_budget_request_is_checked_against_real_plan_state():
    planner = make_planner([])
    goal = Goal(description="完成两步", status=GoalStatus.RUNNING)
    goal.plans.append(Plan(goal_id=goal.id, revision=1, steps=[
        PlanStep(description="第一步", status=StepStatus.COMPLETED),
        PlanStep(description="第二步"),
    ]))
    with provider_budget_scope(8, policy=BudgetPolicy(1000, 400, 200, 1600, 200)) as budget:
        record_provider_tokens(780)
        rejected = await planner._handle_control(goal, ToolCall(
            id="budget-bad", name="request_budget_extension",
            arguments={"reason": "还要继续", "remaining_actions": 0,
                       "estimated_extra_tokens": 300, "stage": "tool_execution"},
        ))
        assert rejected.error == "no_remaining_action" or rejected.error == "remaining_actions_mismatch"
        approved = await planner._handle_control(goal, ToolCall(
            id="budget-good", name="request_budget_extension",
            arguments={"reason": "第二步还未完成", "remaining_actions": 1,
                       "estimated_extra_tokens": 300, "stage": "tool_execution"},
        ))
    assert approved.success is True
    assert budget.extension_count == 1


@pytest.mark.asyncio
async def test_multi_step_plan_executes_tools_and_finishes():
    planner = make_planner([
        call("create_plan", {"steps": ["计算", "复述"]}),
        call("calculator", {"expression": "17*23"}),
        call("echo", {"message": "完成"}),
        call("finish_task", {"summary": "结果是 391，且已完成复述。"}),
    ])
    response = await planner.run("计算后复述")
    assert response.status == GoalStatus.COMPLETED
    assert "391" in response.content
    goal = await planner.store.get(response.goal_id)
    assert [step.status.value for step in goal.current_plan.steps] == ["completed", "completed"]
    events = [event.event_type for event in planner.trace.events(goal.id)]
    assert events.count("observation_received") == 2
    assert events[-1] == "task_completed"


class EmptyInput(BaseModel):
    pass


class FlakyTool(Tool):
    name = "flaky"
    description = "第一次暂时失败，第二次成功"
    input_model = EmptyInput

    def __init__(self):
        self.calls = 0

    async def execute(self, arguments):
        self.calls += 1
        if self.calls == 1:
            return ToolResult(
                success=False,
                content="暂时失败",
                error="temporary",
                metadata={"retryable": True},
            )
        return ToolResult(success=True, content="重试成功")


@pytest.mark.asyncio
async def test_retryable_tool_failure_is_retried():
    registry = ToolRegistry()
    flaky = FlakyTool()
    registry.register(flaky)
    planner = make_planner([
        call("create_plan", {"steps": ["执行不稳定工具"]}),
        call("flaky", {}),
        call("finish_task", {"summary": "已恢复。"}),
    ], registry=registry)
    response = await planner.run("测试恢复")
    assert response.status == GoalStatus.COMPLETED
    assert flaky.calls == 2
    assert "step_retried" in [event.event_type for event in planner.trace.events(response.goal_id)]


@pytest.mark.asyncio
async def test_failed_step_can_be_replanned_with_revision_history():
    planner = make_planner([
        call("create_plan", {"steps": ["调用缺失工具"]}),
        call("missing", {}),
        call("replan", {"steps": ["改用 echo"], "reason": "首选工具不存在"}),
        call("echo", {"message": "fallback"}),
        call("finish_task", {"summary": "已通过替代方案完成。"}),
    ])
    response = await planner.run("尝试并回退")
    goal = await planner.store.get(response.goal_id)
    assert response.status == GoalStatus.COMPLETED
    assert [plan.revision for plan in goal.plans] == [1, 2]
    assert goal.plans[0].steps[0].status.value == "skipped"


@pytest.mark.asyncio
async def test_failed_tool_can_fallback_within_same_step():
    planner = make_planner([
        call("create_plan", {"steps": ["取得结果"]}),
        call("missing", {}),
        call("echo", {"message": "fallback"}),
        call("finish_task", {"summary": "替代工具完成。"}),
    ])
    response = await planner.run("使用可用工具取得结果")
    events = [event.event_type for event in planner.trace.events(response.goal_id)]
    assert response.status == GoalStatus.COMPLETED
    assert "fallback_selected" in events


@pytest.mark.asyncio
async def test_wait_for_user_resume_and_cancel_are_supported():
    planner = make_planner([
        call("create_plan", {"steps": ["获取公司名称", "汇总"]}),
        call("request_user_input", {"question": "公司叫什么？", "missing_fields": ["company"]}),
        call("echo", {"message": "OpenAI"}),
        call("echo", {"message": "准备建议"}),
        call("finish_task", {"summary": "准备完成。"}),
    ])
    waiting = await planner.run("准备面试")
    assert waiting.status == GoalStatus.WAITING_FOR_USER
    assert waiting.input_request.question == "公司叫什么？"
    completed = await planner.resume(waiting.goal_id, "OpenAI")
    assert completed.status == GoalStatus.COMPLETED

    other = make_planner([
        call("create_plan", {"steps": ["等待信息"]}),
        call("request_user_input", {"question": "补充？"}),
    ])
    pending = await other.run("等待再取消")
    cancelled = await other.cancel(pending.goal_id)
    assert cancelled.status == GoalStatus.CANCELLED
    assert (await other.cancel(pending.goal_id)).status == GoalStatus.CANCELLED
