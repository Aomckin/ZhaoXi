from __future__ import annotations

from types import SimpleNamespace

import pytest

from zhaoxi.core.message import Message, Role
from zhaoxi.internal_activity.runtime import InternalActivityRuntime
from zhaoxi.cognitive_stream import ExperienceStream, CognitiveEvent, CognitiveEventType


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
        current_cognition=SimpleNamespace(state=lambda: SimpleNamespace(overview="", threads=[], last_processed_message_id=None)),
    )
    stream = ExperienceStream(tmp_path / "experience.db")
    for content in ("朝汐开发", "继续开发"):
        stream.append(CognitiveEvent(
            event_type=CognitiveEventType.USER_MESSAGE, source="desktop",
            actor_role="OWNER", trust_level="TRUSTED", content=content,
        ))
    agent.experience_stream = stream
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


@pytest.mark.parametrize("event_type", [CognitiveEventType.USER_MESSAGE, CognitiveEventType.EXTERNAL_MESSAGE])
@pytest.mark.parametrize("content", [None, "", " \t\n"])
def test_pending_text_count_accepts_empty_image_events(tmp_path, event_type, content):
    from zhaoxi.cognitive_stream.models import EventPart
    activity = runtime(tmp_path)
    stream = activity.agent.experience_stream
    stream.append(CognitiveEvent(event_type=event_type, source="desktop" if event_type == CognitiveEventType.USER_MESSAGE else "qq",
        actor_role="OWNER", trust_level="TRUSTED", content=content,
        parts=[EventPart(type="image", url="https://image.test/photo.jpg")]))
    stream.append(CognitiveEvent(event_type=CognitiveEventType.SYSTEM_EVENT, source="desktop",
        actor_role="OWNER", content="系统文字"))
    stream.append(CognitiveEvent(event_type=event_type, source="qq", actor_role="OTHER", content="群友文字"))
    assert activity._pending_turns() == 2
    assert len(stream.recent(200)) == 5  # Image event is retained, not deleted or replaced with filler.


@pytest.mark.asyncio
async def test_only_images_do_not_trigger_text_cognition_bootstrap(tmp_path):
    from zhaoxi.cognitive_stream.models import EventPart
    from zhaoxi.internal_activity.activities.legacy import COGNITION, cognition_due
    from datetime import UTC, datetime
    activity = runtime(tmp_path)
    activity.agent.experience_stream = ExperienceStream(tmp_path / "images-only.db")
    for content in [None, "", " \t"]:
        activity.agent.experience_stream.append(CognitiveEvent(event_type=CognitiveEventType.USER_MESSAGE,
            source="desktop", actor_role="OWNER", trust_level="TRUSTED", content=content,
            parts=[EventPart(type="image", url="https://image.test/photo.jpg")]))
    assert await cognition_due(activity, datetime.now(UTC)) is None
    async def execute(name, kind):
        assert name != COGNITION
        return "NO_CHANGE"
    activity._execute = execute
    await activity.run_tick()
    assert activity.state[COGNITION]["failure_count"] == 0
    assert activity.last_skipped[COGNITION] == "clean"


def test_pending_text_count_honors_cursor_with_image_events(tmp_path):
    activity = runtime(tmp_path)
    stream = activity.agent.experience_stream
    state = activity.agent.current_cognition.state()
    state.last_processed_message_id = stream.events_after(None, limit=200)[-1].event_id
    activity.agent.current_cognition.state = lambda: state
    stream.append(CognitiveEvent(event_type=CognitiveEventType.EXTERNAL_MESSAGE, source="qq",
        actor_role="OWNER", content=None))
    stream.append(CognitiveEvent(event_type=CognitiveEventType.USER_MESSAGE, source="desktop",
        actor_role="OWNER", trust_level="TRUSTED", content="最近继续开发"))
    assert activity._pending_turns() == 1
