from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

from tools.lifehud_tool.proactive import LifeHudSensor

NOW = datetime(2026, 9, 5, 4, tzinfo=UTC)


class Client:
    def __init__(self):
        self.calls = []
        self.active = NS(id='session-1', status='RUNNING', title='写代码', actualMinutes=80)
        self.items = [NS(id='task-1', completed=False, name='功能开发')]

    async def focus(self):
        self.calls.append('focus')
        return NS(focus=NS(active=self.active, effectiveMinutes=80))

    async def tasks(self):
        self.calls.append('tasks')
        return NS(date=NOW.date(), tasks=NS(items=self.items, completed=0))


async def test_focus_threshold_cache_and_task_changes():
    client = Client()
    sensor = LifeHudSensor(client)
    assert await sensor.collect(NOW) == []
    client.active.actualMinutes = 100
    client.items[0].completed = True
    assert await sensor.collect(NOW + timedelta(seconds=30)) == []
    assert client.calls == ['focus', 'tasks']
    events = await sensor.collect(NOW + timedelta(minutes=2))
    assert [e.event_type for e in events] == ['focus.long_running', 'task.completed']
    assert events[0].payload['minutes'] == 100
    assert sensor.focus_active and sensor.healthy
    again = await sensor.collect(NOW + timedelta(minutes=4))
    assert again == []
    client.active = None
    assert await sensor.collect(NOW + timedelta(minutes=6)) == []
    assert not sensor.focus_active and sensor.active_focus_id is None


async def test_lifehud_failure_invalidates_cached_health():
    client = Client()
    sensor = LifeHudSensor(client)
    await sensor.collect(NOW)
    async def offline():
        raise RuntimeError('offline')
    client.focus = offline
    try:
        await sensor.collect(NOW + timedelta(minutes=2))
    except RuntimeError:
        pass
    assert not sensor.healthy
    assert await sensor.collect(NOW + timedelta(minutes=2, seconds=30)) == []
