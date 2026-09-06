"""Optional read-only LifeHUD sensor; bounded snapshots, no full today payload."""
from datetime import timedelta
from zhaoxi.proactive.models import ProactiveEvent, Priority


class LifeHudSensor:
    def __init__(self, client):
        self.client = client
        self.next_poll = None
        self.focus_active = False
        self.active_focus_id = None
        self.last_long_focus_id = None
        self.healthy = False
        self.context = ''
        self.tasks = None
        self.day = None

    async def collect(self, now):
        if self.next_poll and now < self.next_poll:
            return []
        self.next_poll = now + timedelta(minutes=2)
        self.healthy = False
        focus = (await self.client.focus()).focus
        tasks_response = await self.client.tasks()
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
        return events
