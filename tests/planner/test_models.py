import pytest

from zhaoxi.errors import InvalidStateTransitionError
from zhaoxi.planner.models import Goal, GoalStatus, PlanStep, StepStatus
from zhaoxi.planner.store import InMemoryPlanStore
from zhaoxi.planner.trace import TraceRecorder


def test_goal_and_step_transitions_are_guarded():
    goal = Goal(description="完成任务")
    goal.transition(GoalStatus.PLANNING)
    goal.transition(GoalStatus.RUNNING)
    goal.transition(GoalStatus.COMPLETED)
    with pytest.raises(InvalidStateTransitionError):
        goal.transition(GoalStatus.RUNNING)

    step = PlanStep(description="第一步")
    step.transition(StepStatus.RUNNING)
    step.transition(StepStatus.FAILED)
    step.transition(StepStatus.PENDING)
    assert step.status == StepStatus.PENDING


@pytest.mark.asyncio
async def test_store_returns_copies_and_trace_is_bounded():
    store = InMemoryPlanStore()
    goal = Goal(description="测试")
    await store.save(goal)
    loaded = await store.require(goal.id)
    loaded.description = "已修改"
    assert (await store.require(goal.id)).description == "测试"

    trace = TraceRecorder(max_events=2)
    trace.record(goal, "one")
    trace.record(goal, "two")
    trace.record(goal, "three")
    assert [event.event_type for event in trace.events(goal.id)] == ["two", "three"]
