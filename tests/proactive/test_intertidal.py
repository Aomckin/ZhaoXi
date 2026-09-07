from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from ctypes.wintypes import RECT

import pytest

from zhaoxi.config.settings import Settings
from zhaoxi.desktop.presence import DesktopPresenceSensor, covers_monitor
from zhaoxi.proactive.interaction import Interaction, InteractionState as Mode, PresenceSnapshot
from zhaoxi.proactive.policy import PolicyState, InterruptPolicy
from zhaoxi.proactive.models import ProactiveEvent, Priority
from zhaoxi.proactive.scoring import score_event
from zhaoxi.proactive.heartbeat import TidalHeartbeat
from zhaoxi.proactive.runtime import ProactiveRuntime
from zhaoxi.proactive.scheduler import Scheduler
from zhaoxi.proactive.store import InMemoryProactiveStore
from zhaoxi.proactive.notifications import InboxNotificationSink
from zhaoxi.proactive.worker import DecisionWorker
from zhaoxi.proactive.decision import Decision
from zhaoxi.reliability.metrics import MetricRegistry

NOW = datetime(2026, 9, 6, 4, tzinfo=UTC)


def test_interaction_decay_and_refresh():
    state = Interaction()
    state.interact(NOW)
    assert state.state == Mode.ACTIVE
    state.interact(NOW + timedelta(minutes=19))
    assert state.refresh(NOW + timedelta(minutes=30)) == Mode.ACTIVE
    assert state.refresh(NOW + timedelta(minutes=39)) == Mode.SEMI_ACTIVE
    assert state.refresh(NOW + timedelta(minutes=84)) == Mode.IDLE
    assert [e[0] for e in state.pending_events] == ['conversation.started', 'conversation.cooled']


def test_window_activation_does_not_override_locked_desktop():
    state = Interaction()
    state.observe(PresenceSnapshot(locked=True), NOW)
    state.window_opened.set()
    state.observe(PresenceSnapshot(locked=True), NOW + timedelta(minutes=1))
    assert state.state == Mode.AWAY
    assert not any(name == 'user.returned' for name, _ in state.pending_events)


@pytest.mark.parametrize('snapshot', [PresenceSnapshot(last_input_seconds=1800), PresenceSnapshot(locked=True)])
def test_away_return_is_one_transition_and_decays(snapshot):
    state = Interaction()
    state.interact(NOW)
    state.observe(snapshot, NOW)
    assert state.state == Mode.AWAY
    state.observe(PresenceSnapshot(), NOW + timedelta(minutes=1))
    assert state.state == Mode.SEMI_ACTIVE
    for i in range(2, 5):
        state.observe(PresenceSnapshot(), NOW + timedelta(minutes=i))
    assert [e[0] for e in state.pending_events].count('user.returned') == 1
    assert state.refresh(NOW + timedelta(minutes=46)) == Mode.IDLE


def test_foreground_fullscreen_changes_and_snapshot_privacy():
    state = Interaction()
    state.observe(PresenceSnapshot(foreground_process='editor.exe'), NOW)
    state.observe(PresenceSnapshot(foreground_process='browser.exe', fullscreen=True), NOW + timedelta(minutes=1))
    state.observe(PresenceSnapshot(foreground_process='browser.exe', fullscreen=True), NOW + timedelta(minutes=2))
    state.observe(PresenceSnapshot(foreground_process='browser.exe'), NOW + timedelta(minutes=3))
    events = [e[0] for e in state.pending_events]
    assert events.count('fullscreen.entered') == events.count('fullscreen.exited') == 1
    assert events.count('foreground.changed') == 1
    assert state.state == Mode.SEMI_ACTIVE
    assert set(asdict(state.snapshot)) == {'last_input_seconds', 'foreground_process', 'fullscreen', 'locked', 'healthy'}
    assert state.diagnostics(NOW + timedelta(minutes=3))['foreground_duration'] == 120


def test_fullscreen_geometry_supports_secondary_monitor_and_maximized_work_area():
    monitor = RECT(-1920, 0, 0, 1080)
    assert covers_monitor(RECT(-1920, 0, 0, 1080), monitor)
    assert not covers_monitor(RECT(-1920, 0, 0, 1040), monitor)


async def test_presence_reader_failure_and_metadata():
    def broken():
        raise OSError('not available')
    assert not (await DesktopPresenceSensor(broken).sample()).healthy
    expected = PresenceSnapshot(last_input_seconds=120, foreground_process='editor.exe')
    assert await DesktopPresenceSensor(lambda: expected).sample() == expected


def gate(state, event=None):
    event = event or ProactiveEvent(event_type='life.change', source='test', importance=.8, urgency=.2)
    return score_event(event, NOW.astimezone(ZoneInfo("Asia/Shanghai")), state, InterruptPolicy(), None, 45)


def test_dynamic_thresholds_away_fullscreen_and_explicit_reminders():
    state = PolicyState()
    assert gate(state).hint == 'inbox'  # .62 < IDLE .70
    state.interaction.interact(NOW)
    assert gate(state).hint == 'candidate'
    state.interacting = True
    assert gate(state).hint == 'defer'
    state.interacting = False
    state.interaction.observe(PresenceSnapshot(fullscreen=True), NOW)
    assert gate(state).hint == 'defer'
    state.interaction.observe(PresenceSnapshot(locked=True), NOW)
    assert gate(state).hint == 'inbox'
    reminder = ProactiveEvent(event_type='reminder.due', source='test')
    assert gate(state, reminder).hint == 'urgent'
    state.quiet_until = NOW + timedelta(hours=1)
    assert gate(state, reminder).hint == 'defer'
    reminder.priority = Priority.URGENT
    assert gate(state, reminder).hint == 'urgent'


def heartbeat(**options):
    store = InMemoryProactiveStore()
    runtime = ProactiveRuntime(store, InboxNotificationSink(store), InterruptPolicy())
    settings = Settings(_env_file=None, proactive_event_buffer_seconds=0, **options)
    return TidalHeartbeat(runtime, Scheduler(store, clock=SimpleNamespace(now=lambda: NOW)),
                          PolicyState(), settings, MetricRegistry(), active=lambda: True)


async def test_heartbeat_transition_events_are_deduped_and_expire():
    h = heartbeat(proactive_natural_checkin_enabled=False)
    h.presence = DesktopPresenceSensor(lambda: PresenceSnapshot(locked=True))
    await h.tick(NOW)
    h.presence = DesktopPresenceSensor(lambda: PresenceSnapshot())
    await h.tick(NOW + timedelta(minutes=1))
    await h.tick(NOW + timedelta(minutes=2))
    events = await h.runtime.store.pending_events()
    assert [e.event_type for e in events] == ['user.returned']
    assert events[0].expires_at == NOW + timedelta(minutes=31)
    assert events[0].payload['last_seen']
    assert not await h.buffer.ready(NOW + timedelta(hours=1))


@pytest.mark.parametrize('mode, expected', [(Mode.ACTIVE, False), (Mode.SEMI_ACTIVE, True), (Mode.IDLE, False), (Mode.AWAY, False)])
async def test_checkin_uses_interaction_state(mode, expected):
    h = heartbeat()
    async def collect(now):
        return []
    h.sensors = [SimpleNamespace(focus_active=False, healthy=True, context='今天完成了一个任务', collect=collect)]
    h.state.last_interaction_at = NOW - timedelta(hours=1)
    if mode == Mode.ACTIVE:
        h.state.interaction.interact(NOW)
    elif mode == Mode.SEMI_ACTIVE:
        h.state.interaction.receptive(NOW)
    elif mode == Mode.AWAY:
        h.state.interaction.observe(PresenceSnapshot(locked=True), NOW)
    await h.tick(NOW)
    assert any(e.event_type == 'natural_checkin' for e in await h.runtime.store.pending_events()) is expected


async def test_fullscreen_entered_during_model_call_is_rechecked():
    h = heartbeat()
    h.presence = DesktopPresenceSensor(lambda: PresenceSnapshot())
    async def decide(events, now, state):
        h.presence = DesktopPresenceSensor(lambda: PresenceSnapshot(fullscreen=True))
        return Decision(action='speak', content='先休息一下吧。')
    await h.buffer.add(ProactiveEvent(event_type='life.change', source='test', importance=1, urgency=1,
                                      occurred_at=NOW, received_at=NOW))
    worker = DecisionWorker(h, SimpleNamespace(decide=decide))
    assert not await worker.tick(NOW)
    assert not await h.runtime.store.list_deliveries()
    assert (await h.runtime.store.pending_events())[0].attempts == 1
