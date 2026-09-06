"""Cheap world observation; model decisions are owned by a separate worker."""
import asyncio
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo
from zhaoxi.proactive.buffer import EventBuffer
from zhaoxi.proactive.models import ProactiveEvent
from zhaoxi.proactive.sensors import computer_active




class TidalHeartbeat:
    def __init__(self, runtime, scheduler, state, settings, metrics, sensors=(), active=computer_active):
        self.runtime, self.scheduler, self.state = runtime, scheduler, state
        self.settings, self.metrics = settings, metrics
        self.sensors, self.active = list(sensors), active
        self.buffer = EventBuffer(runtime.store, settings.proactive_event_buffer_seconds)
        self.started_at = datetime.now(UTC)
        self.focus_active = False
        self.updated = asyncio.Event()

    async def tick(self, now=None):
        now = now or datetime.now(UTC)
        self.metrics.increment('proactive.heartbeat')
        # Scheduler already persists its events using unique schedule occurrence keys.
        scheduled = await self.scheduler.tick()
        self.metrics.increment('proactive.sensor_events', len(scheduled))
        if not self.state.enabled:
            return
        for sensor in self.sensors:
            try:
                candidates = await asyncio.wait_for(sensor.collect(now), 8)
                for event in candidates:
                    if await self.buffer.add(event):
                        self.metrics.increment('proactive.sensor_events')
            except Exception:
                self.metrics.increment('proactive.sensor_errors')
        self.focus_active = any(s.focus_active for s in self.sensors)
        quiet = self.state.quiet_until and self.state.quiet_until > now
        recent = self.state.last_interaction_at or self.started_at
        context = ' '.join(s.context for s in self.sensors if s.healthy)
        active = self.active()
        if (self.settings.proactive_natural_checkin_enabled and not quiet and active
                and not self.state.interacting and not self.focus_active and context
                and all(s.healthy for s in self.sensors)
                and now - recent >= timedelta(hours=self.settings.proactive_natural_checkin_min_hours)):
            day = now.astimezone(ZoneInfo(self.settings.proactive_timezone)).date()
            if await self.buffer.add(ProactiveEvent(
                event_type='natural_checkin', source='heartbeat', occurred_at=now, received_at=now,
                dedupe_key=f'natural-checkin:{day}', importance=.8, urgency=.2,
                expires_at=now + timedelta(hours=1), payload={'summary': context[:600]},
            )):
                self.metrics.increment('proactive.sensor_events')

    async def run(self):
        while True:
            try:
                await self.tick()
            except Exception:
                self.metrics.increment('proactive.heartbeat_errors')
            self.updated.set()
            await asyncio.sleep(self.settings.proactive_heartbeat_seconds)
