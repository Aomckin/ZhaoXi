from __future__ import annotations

from types import SimpleNamespace

import pytest

from zhaoxi.core.message import Message, Role
from zhaoxi.internal_activity.runtime import InternalActivityRuntime


def runtime(tmp_path):
    settings = SimpleNamespace(
        internal_activity_enabled=True, internal_activity_max_llm_per_tick=1,
        internal_activity_max_local_per_tick=3,
        current_cognition_consolidation_enabled=True,
        current_cognition_consolidation_min_turns=2,
        current_cognition_bootstrap_min_turns=2,
        current_cognition_consolidation_min_interval_minutes=30,
        current_cognition_consolidation_max_hours=24,
        memory_maintenance_enabled=True, memory_maintenance_min_interval_minutes=60,
        agenda_maintenance_enabled=True, agenda_maintenance_min_interval_minutes=15,
        proactive_activity_enabled=True,
    )
    agent = SimpleNamespace(
        conversation=SimpleNamespace(messages=[
            Message(role=Role.USER, content="朝汐开发", message_id="u1"),
            Message(role=Role.USER, content="继续开发", message_id="u2"),
        ]),
        current_cognition=SimpleNamespace(state=lambda: SimpleNamespace(narrative="", observations=[])),
    )
    return InternalActivityRuntime(agent, settings, tmp_path / "activity.db")


@pytest.mark.asyncio
async def test_budget_keeps_other_llm_activity_pending(tmp_path):
    activity = runtime(tmp_path)
    async def memory_due(_):
        return True
    activity._memory_due = memory_due
    ran = []
    async def execute(name, kind):
        ran.append(name)
        return [] if name == "proactive_check" else "UPDATE"
    activity._execute = execute
    await activity.run_tick()
    assert "agenda_maintenance" in ran
    assert "current_cognition_consolidation" in ran
    assert "memory_maintenance" not in ran
    assert activity.diagnostics()["skipped"]["memory_maintenance"] == "budget"


@pytest.mark.asyncio
async def test_failure_isolated_and_persisted(tmp_path):
    activity = runtime(tmp_path)
    async def memory_due(_):
        return False
    activity._memory_due = memory_due
    async def execute(name, kind):
        if name == "current_cognition_consolidation":
            raise ValueError("bad model response")
        return [] if name == "proactive_check" else "NO_CHANGE"
    activity._execute = execute
    await activity.run_tick()
    assert activity.state["current_cognition_consolidation"]["failure_count"] == 1
    assert activity.state["agenda_maintenance"]["last_result"] == "NO_CHANGE"
    restored = InternalActivityRuntime(activity.agent, activity.settings, activity.path)
    assert restored.state["current_cognition_consolidation"]["dirty"] is True
