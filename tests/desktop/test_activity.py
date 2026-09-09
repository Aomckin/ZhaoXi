"""Privacy, rates, transitions, inference gates and continuation regression tests."""
import asyncio
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
import inspect
import json
from types import SimpleNamespace

import pytest
from zhaoxi.config.settings import Settings
from zhaoxi.desktop.activity import DesktopActivity, InputCounters
from zhaoxi.desktop.input_hooks import InputHooks
from zhaoxi.desktop.presence import DesktopSnapshot, read_presence
from zhaoxi.proactive.interaction import Interaction, InteractionState, Interruptibility, PresenceSnapshot

NOW = datetime(2026, 9, 8, 12, tzinfo=UTC)


def config(**kwargs):
    return Settings(_env_file=None, **kwargs)


def test_rates_are_per_minute_bounded_and_contain_only_counts():
    clock = [0.]
    counters = InputCounters(lambda: clock[0])
    for _ in range(120):
        counters.count('keyboard')
    counters.count('mouse')
    clock[0] = 59
    assert counters.shape().keyboard_rate_1m == 120
    assert counters.shape().keyboard_rate_5m == 24
    assert counters.shape().mouse_rate_1m == 1
    clock[0] = 60
    assert counters.shape().keyboard_rate_1m == 0
    assert counters.shape().keyboard_rate_5m == 24
    for i in range(1000):
        clock[0] = i + 61
        counters.count('mouse')
    assert len(counters.buckets['mouse']) <= 301
    assert counters.shape().keyboard_rate_5m == 0
    assert all(isinstance(t, int) and isinstance(n, int) for t, n in counters.buckets['mouse'])


def test_hooks_never_dereference_input_payload():
    source = inspect.getsource(InputHooks)
    callback = source.split('def callback(')[1].split('handler =')[0]
    assert 'self.counters.count(channel)' in callback
    assert 'cast(' not in callback and 'contents' not in callback
    assert callback.count('payload') == 2  # signature and required CallNextHookEx forwarding only


def test_titles_switches_retention_and_privacy():
    clock = [0.]
    activity = DesktopActivity(config(), InputCounters(lambda: clock[0]))
    activity.update(DesktopSnapshot(foreground_process='Code.exe', foreground_title='secret-title', foreground_window=1), NOW)
    clock[0] = 10
    activity.update(DesktopSnapshot(foreground_process='browser.exe', foreground_title='second', foreground_window=2), NOW+timedelta(seconds=10))
    assert activity.context.input_shape.window_switch_rate_1m == 1
    assert activity.context.recent_windows[0]['window_title'] == 'secret-title'
    assert activity.context.recent_windows[0]['duration'] == 10
    interaction = Interaction()
    interaction.observe(DesktopSnapshot(foreground_title='secret-title'), NOW)
    assert 'secret-title' not in json.dumps(interaction.diagnostics(NOW), default=str)
    assert 'secret-title' not in json.dumps(activity.diagnostics(), default=str)
    assert 'secret-title' in json.dumps(activity.inspect(), default=str)
    activity.update(DesktopSnapshot(foreground_window=2, foreground_process='browser.exe', foreground_title='second'), NOW+timedelta(minutes=21))
    assert not activity.windows
    activity.update(PresenceSnapshot(locked=True), NOW+timedelta(minutes=22))
    assert not activity.context.desktop_available and not activity.windows
    assert activity.context.foreground_title is None
    assert not DesktopActivity(config()).windows


def test_title_disabled_and_reader_only_uses_foreground():
    activity = DesktopActivity(config(desktop_activity_window_title_enabled=False))
    activity.update(DesktopSnapshot(foreground_title='private', foreground_window=1), NOW)
    activity.update(DesktopSnapshot(foreground_title='other', foreground_window=2), NOW+timedelta(seconds=2))
    assert activity.context.foreground_title is None and not activity.windows
    source = inspect.getsource(read_presence)
    assert 'GetForegroundWindow' in source and 'GetWindowTextW' in source
    assert 'QueryFullProcessImageNameW' in source and 'EnumWindows' not in source


def test_active_high_input_defers_then_resumes_and_deep_work_candidate():
    clock = [0.]
    activity = DesktopActivity(config(desktop_activity_deep_work_seconds=60), InputCounters(lambda: clock[0]))
    state = Interaction()
    state.interact(NOW)
    for second in range(0, 91, 10):
        clock[0] = second
        for _ in range(100):
            activity.counters.count('keyboard')
        snapshot = DesktopSnapshot(foreground_window=1)
        now = NOW+timedelta(seconds=second)
        activity.update(snapshot, now)
        state.observe(snapshot, now)
        state.observe_signals(activity.signals(now), now)
    assert state.state == InteractionState.ACTIVE
    assert state.interruptibility == Interruptibility.LOW
    assert not state.can_continue(now, cooldown_minutes=5, budget=3)
    clock[0] = 160
    now = NOW+timedelta(seconds=160)
    activity.update(DesktopSnapshot(last_input_seconds=70, foreground_window=1), now)
    state.observe_signals(activity.signals(now), now)
    assert state.can_continue(now, cooldown_minutes=5, budget=3)
    assert any(t.event_type == 'activity.deep_work_ended' for t in activity.pending)
    assert activity.context.input_shape.keyboard_rate_5m > 0
    assert activity.context.input_shape.keyboard_rate_1m == 0


@pytest.mark.parametrize('process,title,mode', [
    ('Code.exe', 'work.py', 'text_production'),
    ('Code.exe', 'work.py', 'reading'),
    ('browser.exe', 'research', 'mixed_work'),
    ('browser.exe', 'episode 17', 'media_consumption'),
    ('anything.exe', 'game', 'gaming'),
])
def test_semantics_are_model_hypotheses_not_app_mapping(process, title, mode):
    async def run():
        calls = []
        class Provider:
            async def generate(self, messages):
                calls.append(messages)
                return SimpleNamespace(content=json.dumps({'primary_activity': '可能在工作', 'confidence': .75,
                    'alternative_hypotheses': ['也可能在学习'], 'reason_summary': '结合行为形状', 'activity_mode': mode}))
        activity = DesktopActivity(config())
        activity.update(DesktopSnapshot(foreground_process=process, foreground_title=title, foreground_window=1), NOW)
        activity.update(DesktopSnapshot(foreground_process=process, foreground_title=title, foreground_window=1), NOW+timedelta(seconds=12))
        await activity.infer(Provider(), Interaction(), NOW+timedelta(seconds=12), '刚才在修改项目')
        assert activity.inference.activity_mode == mode
        assert activity.inference.confidence == .75
        assert title in calls[0][1].content and '刚才在修改项目' in calls[0][1].content
        await activity.infer(Provider(), Interaction(), NOW+timedelta(seconds=13))
        assert len(calls) == 1
        assert not any('lifehud' in line.lower() for line in inspect.getsource(type(activity)).splitlines())
    asyncio.run(run())


def test_invalid_inference_and_failure_are_bounded():
    async def run():
        class Provider:
            calls = 0
            async def generate(self, messages):
                self.calls += 1
                return SimpleNamespace(content='{"confidence": 9}')
        activity, provider = DesktopActivity(config()), Provider()
        activity.update(DesktopSnapshot(), NOW)
        activity.update(DesktopSnapshot(), NOW+timedelta(seconds=12))
        await activity.infer(provider, Interaction(), NOW+timedelta(seconds=12))
        await activity.infer(provider, Interaction(), NOW+timedelta(seconds=14))
        assert activity.inference is None and provider.calls == 1
    asyncio.run(run())

def test_win32_foreground_api_contract(monkeypatch):
    import ctypes
    from zhaoxi.desktop import presence
    calls = []
    class Fn:
        def __init__(self, name, result=1, effect=None):
            self.name, self.result, self.effect = name, result, effect
        def __call__(self, *args):
            calls.append(self.name)
            if self.effect:
                self.effect(*args)
            return self.result
    user = SimpleNamespace(
        GetForegroundWindow=Fn('foreground', 42), GetShellWindow=Fn('shell', 7),
        OpenInputDesktop=Fn('desktop', 8), CloseDesktop=Fn('close_desktop'),
        GetUserObjectInformationW=Fn('desktop_name', effect=lambda handle, kind, name, size, needed: setattr(name, 'value', 'Default')),
        GetWindowThreadProcessId=Fn('pid', effect=lambda hwnd, pid: setattr(pid._obj, 'value', 123)),
        GetWindowRect=Fn('rect', 0), MonitorFromWindow=Fn('monitor', 9), GetMonitorInfoW=Fn('monitor_info'),
        GetLastInputInfo=Fn('idle', effect=lambda info: setattr(info._obj, 'dwTime', 1000)),
        GetWindowTextW=Fn('title', effect=lambda hwnd, buffer, size: setattr(buffer, 'value', 'work.py - editor')),
    )
    kernel = SimpleNamespace(OpenProcess=Fn('process', 10), CloseHandle=Fn('close_process'),
        QueryFullProcessImageNameW=Fn('image', effect=lambda handle, flags, buffer, size: setattr(buffer, 'value', r'C:\Apps\editor.exe')),
        GetTickCount=Fn('ticks', 2000))
    monkeypatch.setattr(presence.sys, 'platform', 'win32')
    monkeypatch.setattr(ctypes, 'WinDLL', lambda name, **kwargs: user if name == 'user32' else kernel)
    snapshot = presence.read_presence(True)
    assert snapshot.foreground_process == 'editor.exe'
    assert snapshot.foreground_title == 'work.py - editor'
    assert snapshot.foreground_window == 42 and snapshot.last_input_seconds == 1
    assert calls.count('foreground') == 1 and 'close_process' in calls
    calls.clear()
    assert presence.read_presence(False).foreground_title is None
    assert 'title' not in calls
    user.OpenInputDesktop.result = 0
    calls.clear()
    assert presence.read_presence(True).locked
    assert 'foreground' not in calls


async def test_sampler_shutdown_cleans_titles_and_hooks():
    from zhaoxi.desktop.presence import DesktopActivitySensor
    state = Interaction()
    sensor = DesktopActivitySensor(config(desktop_activity_input_rate_enabled=False), state,
        reader=lambda: DesktopSnapshot(foreground_title='private', foreground_window=1))
    task = asyncio.create_task(sensor.run())
    for _ in range(100):
        if sensor.activity.context:
            break
        await asyncio.sleep(.001)
    assert sensor.activity.context.foreground_title == 'private'
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sensor.activity.context is None and not sensor.activity.windows

def test_desktop_inspect_requires_token_and_diagnostics_hide_titles():
    from fastapi.testclient import TestClient
    from zhaoxi.web.app import create_app
    from zhaoxi.core.conversation import Conversation
    from zhaoxi.proactive.policy import PolicyState
    activity = DesktopActivity(config())
    activity.update(DesktopSnapshot(foreground_title='private title'), NOW)
    state = PolicyState()
    state.interaction.desktop_activity = activity
    state.interaction.observe(DesktopSnapshot(foreground_title='private title'), NOW)
    agent = SimpleNamespace(conversation=Conversation(), proactive_state=state)
    client = TestClient(create_app(agent=agent, settings=config(), api_token='test-secret'))
    assert client.get('/api/desktop/activity/inspect').status_code == 401
    headers = {'X-Zhaoxi-Token': 'test-secret'}
    assert 'private title' in client.get('/api/desktop/activity/inspect', headers=headers).text
    response = client.get('/api/diagnostics', headers=headers)
    assert response.status_code == 200 and 'private title' not in response.text
