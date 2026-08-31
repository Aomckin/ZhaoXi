"""Deterministic persistent schedule evaluation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

from zhaoxi.proactive.models import MisfirePolicy, ProactiveEvent, Schedule, ScheduleKind
from zhaoxi.proactive.store import ProactiveStore


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class Scheduler:
    def __init__(
        self,
        store: ProactiveStore,
        *,
        clock: Clock | None = None,
        max_per_tick: int = 50,
        misfire_grace_seconds: int = 3600,
    ) -> None:
        self.store = store
        self.clock = clock or SystemClock()
        self.max_per_tick = max_per_tick
        self.misfire_grace = timedelta(seconds=misfire_grace_seconds)

    async def tick(self) -> list[ProactiveEvent]:
        now = self.clock.now().astimezone(UTC)
        schedules = await self.store.due_schedules(now, self.max_per_tick)
        emitted: list[ProactiveEvent] = []
        for schedule in schedules:
            event = await self._fire(schedule, now)
            if event is not None:
                emitted.append(event)
        return emitted

    async def _fire(self, schedule: Schedule, now: datetime) -> ProactiveEvent | None:
        due_at = schedule.next_fire_at
        late = now - due_at
        should_emit = True
        if late > self.misfire_grace:
            if schedule.misfire_policy in {MisfirePolicy.SKIP, MisfirePolicy.EXPIRE}:
                should_emit = False

        event = None
        if should_emit:
            dedupe_key = f"schedule:{schedule.schedule_id}:{due_at.isoformat()}"
            candidate = ProactiveEvent(
                event_type=schedule.event_type,
                source=schedule.source,
                occurred_at=due_at,
                received_at=now,
                priority=schedule.priority,
                dedupe_key=dedupe_key,
                correlation_id=schedule.schedule_id,
                payload=schedule.payload,
            )
            if await self.store.add_event(candidate):
                event = candidate

        schedule.last_fired_at = due_at if should_emit else schedule.last_fired_at
        schedule.updated_at = now
        if schedule.kind == ScheduleKind.ONCE or (
            late > self.misfire_grace and schedule.misfire_policy == MisfirePolicy.EXPIRE
        ):
            schedule.enabled = False
        else:
            interval = timedelta(seconds=schedule.interval_seconds or 1)
            next_fire = due_at + interval
            while next_fire <= now:
                next_fire += interval
            schedule.next_fire_at = next_fire
        await self.store.save_schedule(schedule)
        return event

