import pytest

from zhaoxi.planner.models import Goal, GoalStatus
from zhaoxi.planner.models import Plan, PlanStep, StepStatus
from zhaoxi.planner.sqlite import SQLitePlanStore
from zhaoxi.planner.store import InMemoryPlanStore
from zhaoxi.planner.runtime import PlannerRuntime
from zhaoxi.permission.models import InvocationOrigin, PendingConfirmation, PermissionLevel, PermissionRequest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace


@pytest.mark.asyncio
async def test_sqlite_plan_store_survives_restart(tmp_path):
    path = tmp_path / "planner.db"
    store = SQLitePlanStore(path)
    goal = Goal(description="恢复任务")
    goal.transition(GoalStatus.PLANNING)
    goal.transition(GoalStatus.WAITING_FOR_USER)
    await store.save(goal)

    restored = await SQLitePlanStore(path).require(goal.id)
    assert restored.status is GoalStatus.WAITING_FOR_USER
    assert restored.description == "恢复任务"


@pytest.mark.asyncio
async def test_sqlite_plan_store_rejects_newer_schema(tmp_path):
    import sqlite3

    path = tmp_path / "newer.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        connection.execute("INSERT INTO schema_version VALUES (999)")
    with pytest.raises(RuntimeError, match="高于"):
        SQLitePlanStore(path)


@pytest.mark.asyncio
@pytest.mark.parametrize("persistent", [True, False])
async def test_planner_rebuilds_permission_wait(tmp_path, persistent):
    store = SQLitePlanStore(tmp_path / "planner.db") if persistent else InMemoryPlanStore()
    goal = Goal(description="恢复写入")
    step = PlanStep(description="写入", status=StepStatus.RUNNING)
    goal.plans.append(Plan(goal_id=goal.id, revision=1, steps=[step]))
    goal.transition(GoalStatus.PLANNING)
    goal.transition(GoalStatus.RUNNING)
    request = PermissionRequest(
        request_id=goal.id,
        tool_name="write.test",
        permission=PermissionLevel.WRITE,
        arguments={"value": 1},
        arguments_digest="digest",
        resource_scope="test:item",
        action_summary="写入",
        origin=InvocationOrigin.PLANNER,
        goal_id=goal.id,
        step_id=step.id,
    )
    pending = PendingConfirmation(
        request=request,
        question="允许吗",
        risk_summary="写入",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    goal.permission_confirmation = pending
    goal.transition(GoalStatus.WAITING_FOR_PERMISSION)
    await store.save(goal)

    runtime = PlannerRuntime(
        provider=SimpleNamespace(),
        registry=SimpleNamespace(),
        context_builder=SimpleNamespace(),
        store=SQLitePlanStore(tmp_path / "planner.db") if persistent else store,
        tool_executor=SimpleNamespace(),
    )
    restored = runtime._pending_permissions[pending.confirmation_id]
    assert restored.goal_id == goal.id
    assert restored.arguments == {"value": 1}
    assert restored.recovered is True
