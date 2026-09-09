"""Optional LifeHUD providers with shared sampling and unreachable backoff."""
import asyncio
from datetime import timedelta

from zhaoxi.sdk import ProactiveEvent, Priority, StateSignal


class LifeHudSensor:
    BACKOFF_MINUTES = (2, 5, 15, 30)

    def __init__(self, client, *, status_owner=None):
        self.client = client
        self.status_owner = status_owner
        self.next_poll = None
        self.focus_active = False
        self.active_focus_id = None
        self.last_long_focus_id = None
        self.healthy = False
        self.reachable = None
        self.failures = 0
        self.context = ''
        self.tasks = None
        self.day = None

        self._events = []
        self._signals = []
        self._sampled_at = None

    async def _refresh(self, now):
        if self.next_poll and now < self.next_poll:
            return
        self.healthy = False
        try:
            focus = (await self.client.focus()).focus
            tasks_response = await self.client.tasks()
        except (Exception, asyncio.CancelledError):
            self.reachable = False
            self.failures += 1
            delay = self.BACKOFF_MINUTES[min(self.failures - 1, len(self.BACKOFF_MINUTES) - 1)]
            self.next_poll = now + timedelta(minutes=delay)
            self._events = []
            self._signals = []
            raise
        self.next_poll = now + timedelta(minutes=2)
        self.failures = 0
        self.reachable = True
        self.healthy = True
        self.focus_active = bool(focus.active)
        self.active_focus_id = focus.active.id if focus.active else None
        events = []
        if focus.active and focus.active.status == 'RUNNING':
            active = focus.active
            minutes = active.actualMinutes
            if minutes >= 90 and self.last_long_focus_id != active.id:
                self.last_long_focus_id = active.id
                events.append(ProactiveEvent(
                    event_type='focus.long_running', source='lifehud',
                    received_at=now, occurred_at=now,
                    dedupe_key=f'focus-long-running:{active.id}', importance=.8, urgency=.5,
                    payload={'focus_id': active.id, 'minutes': minutes,
                             'summary': f'当前 Focus「{active.title[:120]}」已持续 {minutes} 分钟。'},
                    expires_at=now + timedelta(minutes=5),
                ))
        current = {t.id: t.completed for t in tasks_response.tasks.items[:500]}
        if self.tasks is not None and self.day == tasks_response.date:
            completed = [t for t in tasks_response.tasks.items[:500]
                         if t.completed and self.tasks.get(t.id) is False]
            for task in completed[:20]:
                events.append(ProactiveEvent(
                    event_type='task.completed', source='lifehud', priority=Priority.INFO,
                    received_at=now, occurred_at=now, importance=.5, urgency=.2,
                    dedupe_key=f'task-completed:{tasks_response.date}:{task.id}',
                    payload={'summary': f'今天完成了任务「{task.name[:120]}」。'},
                ))
        self.tasks, self.day = current, tasks_response.date
        self.context = (f'今天已完成 {tasks_response.tasks.completed} 项任务，'
                        f'专注 {focus.effectiveMinutes} 分钟。') if (
                            tasks_response.tasks.completed or focus.effectiveMinutes) else ''
        self._events = events
        self._signals = [StateSignal(
            type="attention.focus",
            value="active" if focus.active else "inactive",
            observed_at=now,
            expires_at=now + timedelta(minutes=3),
            confidence=1.0,
            priority="high",
            source="lifehud",
            metadata={"focus_id": self.active_focus_id},
        )]
        self._sampled_at = now

    async def collect(self, now):
        await self._refresh(now)
        events, self._events = self._events, []
        return events

    async def collect_signals(self, now):
        await self._refresh(now)
        return list(self._signals)
