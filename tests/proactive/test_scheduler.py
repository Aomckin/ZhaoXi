from datetime import UTC, datetime, timedelta

from zhaoxi.proactive.models import MisfirePolicy, ProactiveEvent, Schedule, ScheduleKind
from zhaoxi.proactive.scheduler import Scheduler
from zhaoxi.proactive.sqlite import SQLiteProactiveStore
from zhaoxi.proactive.store import InMemoryProactiveStore


class FakeClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


async def test_once_schedule_emits_exactly_once():
    now = datetime(2026, 8, 31, 4, tzinfo=UTC)
    store = InMemoryProactiveStore()
    schedule = Schedule(
        schedule_id="once-test",
        event_type="reminder.due",
        kind=ScheduleKind.ONCE,
        next_fire_at=now,
    )
    await store.save_schedule(schedule)
    scheduler = Scheduler(store, clock=FakeClock(now))

    first = await scheduler.tick()
    second = await scheduler.tick()

    assert len(first) == 1
    assert second == []
    assert (await store.get_schedule("once-test")).enabled is False


async def test_interval_skips_missed_occurrences_without_storm():
    due = datetime(2026, 8, 31, 1, tzinfo=UTC)
    now = due + timedelta(hours=3)
    store = InMemoryProactiveStore()
    await store.save_schedule(Schedule(
        schedule_id="interval-test",
        event_type="heartbeat",
        kind=ScheduleKind.INTERVAL,
        next_fire_at=due,
        interval_seconds=60,
        misfire_policy=MisfirePolicy.FIRE_ONCE,
    ))

    events = await Scheduler(store, clock=FakeClock(now), misfire_grace_seconds=60).tick()

    assert len(events) == 1
    restored = await store.get_schedule("interval-test")
    assert restored.next_fire_at > now


async def test_expired_misfire_disables_without_event():
    due = datetime(2026, 8, 31, 1, tzinfo=UTC)
    now = due + timedelta(hours=2)
    store = InMemoryProactiveStore()
    await store.save_schedule(Schedule(
        schedule_id="expired",
        event_type="reminder.due",
        kind=ScheduleKind.ONCE,
        next_fire_at=due,
        misfire_policy=MisfirePolicy.EXPIRE,
    ))

    assert await Scheduler(store, clock=FakeClock(now), misfire_grace_seconds=60).tick() == []
    assert (await store.get_schedule("expired")).enabled is False


async def test_event_dedupe_is_enforced():
    store = InMemoryProactiveStore()
    assert await store.add_event(ProactiveEvent(event_type="x", source="test", dedupe_key="same"))
    assert not await store.add_event(ProactiveEvent(event_type="x", source="test", dedupe_key="same"))


async def test_sqlite_round_trip_and_restart(tmp_path):
    path = tmp_path / "proactive.db"
    now = datetime(2026, 8, 31, 4, tzinfo=UTC)
    first = SQLiteProactiveStore(path)
    await first.save_schedule(Schedule(
        schedule_id="persisted",
        event_type="reminder.due",
        kind=ScheduleKind.ONCE,
        next_fire_at=now,
    ))

    restarted = SQLiteProactiveStore(path)
    events = await Scheduler(restarted, clock=FakeClock(now)).tick()
    assert len(events) == 1
    assert await restarted.get_event(events[0].event_id) is not None
    assert (await restarted.get_schedule("persisted")).enabled is False

