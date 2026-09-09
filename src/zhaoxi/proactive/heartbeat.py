"""Cheap world observation; model decisions are owned by a separate worker."""
import asyncio
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo
from zhaoxi.proactive.buffer import EventBuffer
from zhaoxi.proactive.models import ProactiveEvent, Priority, EventStatus
from zhaoxi.proactive.sensors import computer_active
from zhaoxi.proactive.interaction import InteractionState, PresenceSnapshot
from zhaoxi.sdk import StateSignal




class TidalHeartbeat:
    def __init__(self, runtime, scheduler, state, settings, metrics, sensors=(), active=computer_active, presence=None,
                 signal_providers=()):
        self.runtime, self.scheduler, self.state = runtime, scheduler, state
        self.settings, self.metrics = settings, metrics
        self.sensors, self.active = list(sensors), active
        self.signal_providers = list(signal_providers)
        self.buffer = EventBuffer(runtime.store, settings.proactive_event_buffer_seconds)
        self.started_at = datetime.now(UTC)
        self.focus_active = False
        self.updated = asyncio.Event()
        self.presence = presence
        self.continuation = None
        state.interaction.active_minutes = settings.active_timeout_minutes
        state.interaction.semi_active_minutes = settings.semi_active_timeout_minutes
        state.interaction.away_minutes = settings.away_idle_minutes
        state.thresholds = (settings.proactive_threshold_active, settings.proactive_threshold_semi_active,
                            settings.proactive_threshold_idle)

    async def tick(self, now=None):
        now = now or datetime.now(UTC)
        self.metrics.increment('proactive.heartbeat')
        interaction = self.state.interaction
        if self.presence:
            try:
                interaction.observe(await self.presence.sample(), now)
            except Exception:
                interaction.observe(PresenceSnapshot(healthy=False), now)
                self.metrics.increment('proactive.sensor_errors')
        snapshot = interaction.snapshot
        if snapshot and snapshot.healthy:
            interaction.observe_signals([
                StateSignal(type="desktop.fullscreen", value=snapshot.fullscreen, source="desktop",
                            observed_at=now, expires_at=now + timedelta(minutes=2)),
                StateSignal(type="desktop.locked", value=snapshot.locked, source="desktop",
                            observed_at=now, expires_at=now + timedelta(minutes=2), priority="critical"),
            ], now)
        if self.state.quiet_until and self.state.quiet_until > now:
            interaction.observe_signals([
                StateSignal(type="interruptibility.manual", value="blocked", source="quiet_mode",
                            observed_at=now, expires_at=self.state.quiet_until, priority="critical"),
            ], now)
        interaction.refresh(now)
        # Scheduler already persists its events using unique schedule occurrence keys.
        scheduled = await self.scheduler.tick()
        self.metrics.increment('proactive.sensor_events', len(scheduled))
        if not self.state.enabled:
            interaction.pending_events.clear()
            return
        for sensor in self.sensors:
            try:
                candidates = await asyncio.wait_for(sensor.collect(now), 8)
                for event in candidates:
                    if await self.buffer.add(event):
                        self.metrics.increment('proactive.sensor_events')
            except Exception:
                self.metrics.increment('proactive.sensor_errors')
        for provider in self.signal_providers:
            try:
                interaction.observe_signals(await asyncio.wait_for(provider.collect_signals(now), 8), now)
            except Exception:
                self.metrics.increment('proactive.signal_provider_errors')
        was_focused = self.focus_active
        focus_signal = interaction.signals.resolve("attention.focus", now)
        self.focus_active = bool(focus_signal and focus_signal.value == "active")
        if was_focused != self.focus_active:
            interaction.pending_events.append(('focus.started' if self.focus_active else 'focus.ended', now))
            if not self.focus_active and interaction.state != InteractionState.AWAY:
                interaction.receptive(now)
        summaries = {
            'user.returned': '用户离开一段时间后重新回到电脑前。',
            'activity.deep_work_ended': '用户刚才持续高频操作了一段时间，现在输入明显停止。这只是活动形状，具体在做什么仍不确定。',
            'focus.ended': '用户刚刚结束专注。',
        }
        activity = interaction.desktop_activity
        if activity:
            while activity.pending:
                transition = activity.pending.popleft()
                if transition.event_type == 'activity.deep_work_ended' and interaction.state != InteractionState.AWAY:
                    interaction.receptive(now)
                    if self.continuation:
                        self.continuation.prepare_background('activity', '刚才有一段持续高输入活动，可以在合适时机温和关心；具体活动尚不确定。', now)
                interaction.pending_events.append((transition.event_type, transition.observed_at))
        changes = list(interaction.pending_events)
        interaction.pending_events.clear()
        for name, occurred_at in changes:
            await self.buffer.add(ProactiveEvent(
                event_type=name, source='presence', occurred_at=occurred_at, received_at=now,
                dedupe_key=f'{name}:{occurred_at.isoformat()}', expires_at=now + timedelta(minutes=30),
                importance=.8 if name in summaries else .1, urgency=.2,
                priority=Priority.NOTICE if name in summaries else Priority.INFO,
                status=EventStatus.PENDING if name in summaries else EventStatus.HANDLED,
                payload={'summary': summaries.get(name, ''), 'last_seen': now.isoformat()},
            ))
            self.metrics.increment('interaction.state_events')
        quiet = self.state.quiet_until and self.state.quiet_until > now
        recent = self.state.last_interaction_at or self.started_at
        context = ' '.join(s.context for s in self.sensors if s.healthy)
        if activity and activity.context and activity.context.desktop_available:
            context += ' 用户当前在电脑前，近期有桌面活动，可结合活动上下文判断是否适合关心。'
        snapshot = interaction.snapshot
        active = (snapshot.healthy and not snapshot.locked and snapshot.last_input_seconds < 300) if snapshot else self.active()
        receptive = interaction.state == InteractionState.SEMI_ACTIVE
        minimum = timedelta(minutes=45) if receptive else timedelta(hours=self.settings.proactive_natural_checkin_min_hours)
        if (self.settings.proactive_natural_checkin_enabled and not quiet and active
                and interaction.state not in {InteractionState.ACTIVE, InteractionState.AWAY}
                and not (snapshot and snapshot.fullscreen)
                and not self.state.interacting and not self.focus_active and context
                and all(s.healthy for s in self.sensors)
                and now - recent >= minimum):
            day = now.astimezone(ZoneInfo(self.settings.proactive_timezone)).date()
            if await self.buffer.add(ProactiveEvent(
                event_type='natural_checkin', source='heartbeat', occurred_at=now, received_at=now,
                dedupe_key=f'natural-checkin:{day}', importance=.95, urgency=.4,
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
