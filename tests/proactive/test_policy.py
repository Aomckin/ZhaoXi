from datetime import UTC, datetime, time, timedelta

import pytest

from zhaoxi.proactive.conditions import ConditionError, evaluate
from zhaoxi.proactive.models import (
    DeliveryStatus,
    PolicyAction,
    Priority,
    ProactiveEvent,
    Subscription,
)
from zhaoxi.proactive.notifications import InboxNotificationSink
from zhaoxi.proactive.policy import InterruptPolicy, PolicyState
from zhaoxi.proactive.runtime import ProactiveRuntime
from zhaoxi.proactive.store import InMemoryProactiveStore


def test_condition_dsl_is_bounded_and_whitelisted():
    context = {"payload": {"score": 9, "tags": ["important"]}}
    assert evaluate({"and": [{"gte": ["$.payload.score", 8]}, {"contains": ["$.payload.tags", "important"]}]}, context)
    with pytest.raises(ConditionError, match="不支持"):
        evaluate({"exec": ["anything", True]}, context)


def test_quiet_and_night_policy_are_deterministic():
    now = datetime(2026, 8, 31, 14, tzinfo=UTC)
    notice = ProactiveEvent(event_type="reminder", source="test", priority=Priority.NOTICE)
    quiet = InterruptPolicy().decide(notice, now, PolicyState(quiet_until=now + timedelta(hours=1)))
    assert quiet.action == PolicyAction.DEFER
    urgent = notice.model_copy(update={"priority": Priority.URGENT})
    assert InterruptPolicy().decide(urgent, now, PolicyState(quiet_until=now + timedelta(hours=1))).action == PolicyAction.DELIVER_NOW

    night = datetime(2026, 8, 31, 23, 30, tzinfo=UTC)
    assert InterruptPolicy(night_start=time(23), night_end=time(8)).decide(notice, night, PolicyState()).reason == "night_mode"


def test_event_time_is_distinct_from_recorded_and_known_time():
    happened = datetime(2020, 1, 1, tzinfo=UTC)
    learned = datetime(2026, 9, 14, tzinfo=UTC)
    event = ProactiveEvent(
        event_type="diary.imported",
        source="imported_diary",
        occurred_at=happened,
        received_at=learned,
    )
    assert event.event_at == happened
    assert event.recorded_at == learned
    assert event.known_at == learned
    assert event.source == "imported_diary"


async def test_runtime_delivers_and_deduplicates_delivery():
    now = datetime(2026, 8, 31, 12, tzinfo=UTC)
    store = InMemoryProactiveStore()
    runtime = ProactiveRuntime(
        store,
        InboxNotificationSink(store),
        InterruptPolicy(night_start=time(23), night_end=time(8)),
        [Subscription(
            subscription_id="important-reminder",
            event_type="reminder.due",
            condition={"eq": ["$.payload.enabled", True]},
            notification_template="提醒到了",
        )],
    )
    event = ProactiveEvent(event_type="reminder.due", source="scheduler", payload={"enabled": True})

    first = await runtime.process(event, now, PolicyState())
    second = await runtime.process(event, now, PolicyState())

    assert first[0].status == DeliveryStatus.DELIVERED
    assert len(await store.list_deliveries()) == 1
    assert second[0].status == DeliveryStatus.DELIVERED


async def test_runtime_defers_during_quiet_mode():
    now = datetime(2026, 8, 31, 12, tzinfo=UTC)
    store = InMemoryProactiveStore()
    runtime = ProactiveRuntime(
        store,
        InboxNotificationSink(store),
        InterruptPolicy(),
        [Subscription(subscription_id="s", event_type="x")],
    )
    deliveries = await runtime.process(
        ProactiveEvent(event_type="x", source="test"),
        now,
        PolicyState(quiet_until=now + timedelta(minutes=30)),
    )
    assert deliveries[0].status == DeliveryStatus.DEFERRED
    assert deliveries[0].decision_reason == "quiet_mode"
