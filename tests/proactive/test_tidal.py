import asyncio
from datetime import UTC, datetime, timedelta, time
from types import SimpleNamespace

import pytest

from zhaoxi.config.settings import Settings
from zhaoxi.core.conversation import Conversation
from zhaoxi.interfaces.gateway import InterfaceGateway
from zhaoxi.models.types import ModelResponse
from zhaoxi.proactive.buffer import EventBuffer
from zhaoxi.proactive.decision import Decision, ModelDecision
from zhaoxi.proactive.heartbeat import TidalHeartbeat
from zhaoxi.proactive.models import (
    DeliveryStatus, EventStatus, Priority, ProactiveEvent, Schedule, ScheduleKind, Subscription,
)
from zhaoxi.proactive.notifications import InboxNotificationSink
from zhaoxi.proactive.policy import InterruptPolicy, PolicyState
from zhaoxi.proactive.runtime import ProactiveRuntime
from zhaoxi.proactive.scheduler import Scheduler
from zhaoxi.proactive.scoring import score_event
from zhaoxi.proactive.sqlite import SQLiteProactiveStore
from zhaoxi.proactive.store import InMemoryProactiveStore
from zhaoxi.proactive.worker import DecisionWorker
from zhaoxi.reliability.metrics import MetricRegistry
from zhaoxi.desktop.notifications import DesktopNotificationSink

NOW = datetime(2026, 9, 5, 4, tzinfo=UTC)  # noon Shanghai


class Clock:
    def now(self):
        return NOW


class Decisions:
    def __init__(self, action='speak'):
        self.calls = []
        self.action = action

    async def decide(self, events, now, state):
        self.calls.append(events)
        return Decision(action=self.action, content='暗苟酱，已经专注很久啦，歇一会儿？')


def setup(store=None, action='speak', **options):
    store = store or InMemoryProactiveStore()
    runtime = ProactiveRuntime(store, InboxNotificationSink(store), InterruptPolicy(), [
        Subscription(subscription_id='reminder', event_type='reminder.due',
                     notification_template='提醒：{payload[text]}'),
    ])
    settings = Settings(_env_file=None, proactive_event_buffer_seconds=0, **options)
    h = TidalHeartbeat(runtime, Scheduler(store, clock=Clock()), PolicyState(), settings, MetricRegistry(), active=lambda: True)
    model = Decisions(action)
    return h, DecisionWorker(h, model), model


def candidate(key='focus-1', **kwargs):
    return ProactiveEvent(event_type='focus.long_running', source='test', dedupe_key=key,
                          occurred_at=NOW, received_at=NOW, importance=.8, urgency=.5,
                          payload={'summary': 'Focus 已持续 100 分钟'}, **kwargs)


async def test_empty_heartbeat_never_calls_decision():
    h, worker, model = setup()
    for _ in range(100):
        await h.tick(NOW)
        await worker.tick(NOW)
    assert not model.calls
    assert h.metrics.snapshot()['counters']['proactive.heartbeat'] == 100


async def test_observation_and_decision_are_separate():
    h, worker, model = setup()
    await h.buffer.add(candidate())
    await h.tick(NOW)
    assert not model.calls
    result = await worker.tick(NOW)
    assert result[0].status == DeliveryStatus.DELIVERED
    assert len(model.calls) == 1
    assert h.metrics.snapshot()['counters']['proactive.spoken'] == 1


async def test_buffer_dedupe_expiry_capacity_and_aggregation():
    store = InMemoryProactiveStore()
    buffer = EventBuffer(store, seconds=300, capacity=2)
    assert await buffer.add(candidate())
    assert not await buffer.add(candidate())
    assert not await buffer.ready(NOW)
    await buffer.add(candidate('second'))
    assert len(await buffer.ready(NOW + timedelta(minutes=5))) == 2
    await buffer.add(candidate('third'))
    assert len(await store.pending_events()) == 2
    assert not await buffer.ready(NOW + timedelta(hours=7))


@pytest.mark.parametrize('importance,urgency,hint', [(0.1, 0.1, 'drop'), (.5, .4, 'inbox'), (.9, .7, 'candidate')])
def test_gate_scores(importance, urgency, hint):
    e = candidate()
    e.importance, e.urgency = importance, urgency
    assert score_event(e, NOW, PolicyState(), InterruptPolicy(night_start=time(22), night_end=time(2)), None, 45).hint == hint


@pytest.mark.parametrize('mode', ['quiet', 'cooldown', 'interaction', 'busy'])
async def test_gates_prevent_model_calls(mode):
    h, worker, model = setup()
    if mode == 'quiet':
        h.state.quiet_until = NOW + timedelta(hours=1)
    elif mode == 'interaction':
        h.state.last_interaction_at = NOW
    elif mode == 'busy':
        h.state.interacting = True
    else:
        await h.buffer.add(candidate('previous'))
        await worker.tick(NOW)
        model.calls.clear()
    await h.buffer.add(candidate('new'))
    assert not await worker.tick(NOW + timedelta(seconds=1))
    assert not model.calls


async def test_quiet_release_and_urgent_exception():
    h, worker, model = setup()
    h.state.quiet_until = NOW + timedelta(hours=1)
    await h.buffer.add(candidate())
    await worker.tick(NOW)
    assert not model.calls
    assert await worker.tick(NOW + timedelta(hours=1))
    await h.buffer.add(candidate('urgent', priority=Priority.URGENT))
    h.state.quiet_until = NOW + timedelta(hours=3)
    assert await worker.tick(NOW + timedelta(hours=2))


@pytest.mark.parametrize('action', ['silent', 'defer', 'speak'])
async def test_decision_actions_and_bounded_deferral(action):
    h, worker, model = setup(action=action)
    await h.buffer.add(candidate())
    first = await worker.tick(NOW)
    assert bool(first) == (action == 'speak')
    await worker.tick(NOW + timedelta(seconds=30))
    assert len(model.calls) == 1
    await worker.tick(NOW + timedelta(minutes=31))
    await worker.tick(NOW + timedelta(hours=2))
    assert len(model.calls) == (2 if action == 'defer' else 1)
    assert not await h.runtime.store.pending_events()


async def test_batch_one_model_call_and_restart_deduplication(tmp_path):
    path = tmp_path / 'proactive.db'
    h, worker, model = setup(SQLiteProactiveStore(path))
    await h.buffer.add(candidate())
    await h.buffer.add(candidate('second'))
    result = await worker.tick(NOW)
    assert len(result) == 1 and len(model.calls[0]) == 2
    restored, other, unused = setup(SQLiteProactiveStore(path))
    assert not await restored.buffer.add(candidate())
    assert not await other.tick(NOW + timedelta(hours=2))
    assert not unused.calls
    assert len(await restored.runtime.store.list_deliveries()) == 1


async def test_reminder_once_survives_restart_and_bypasses_buffer(tmp_path):
    path = tmp_path / 'proactive.db'
    h, _, _ = setup(SQLiteProactiveStore(path))
    await h.runtime.store.save_schedule(Schedule(event_type='reminder.due', kind=ScheduleKind.ONCE,
                                                next_fire_at=NOW, payload={'text': '喝水'}))
    await h.tick(NOW)
    restored, worker, model = setup(SQLiteProactiveStore(path))
    restored.buffer.seconds = 600
    result = await worker.tick(NOW)
    assert len(result) == 1 and '喝水' in result[0].content
    await restored.tick(NOW)
    assert not await worker.tick(NOW)
    assert not model.calls


async def test_inbox_does_not_popup_or_call_model():
    h, worker, model = setup()
    popups = []
    h.runtime.sink = DesktopNotificationSink(h.runtime.sink, lambda *args: popups.append(args))
    await h.buffer.add(candidate(priority=Priority.INFO))
    result = await worker.tick(NOW)
    assert result[0].priority == Priority.INFO
    assert not model.calls and not popups


async def test_notification_retry_does_not_repeat_popup():
    h, worker, _ = setup()
    popups = []
    h.runtime.sink = DesktopNotificationSink(h.runtime.sink, lambda *args: popups.append(args))
    await h.buffer.add(candidate())
    delivery = (await worker.tick(NOW))[0]
    await h.runtime.sink.deliver(delivery, NOW)
    assert len(popups) == 1


async def test_activation_restores_background_once():
    h, worker, _ = setup()
    await h.buffer.add(candidate())
    delivery = (await worker.tick(NOW))[0]
    agent = SimpleNamespace(proactive=h.runtime, conversation=Conversation())
    gateway = InterfaceGateway(agent)
    await gateway.activate_delivery(delivery.delivery_id)
    await gateway.activate_delivery(delivery.delivery_id)
    assert len(agent.conversation.messages) == 1
    assert '100 分钟' in agent.conversation.messages[0].background
    assert agent.conversation.messages[0].content == delivery.content
    assert agent.conversation.messages[0].timestamp == delivery.delivered_at
    assert (await h.runtime.store.get_delivery(delivery.delivery_id)).acknowledged_at
    with pytest.raises(KeyError):
        await gateway.activate_delivery('missing')


@pytest.mark.parametrize('content', ['not json', '{"action":"speak","content":""}', '{"action":"destroy"}'])
async def test_invalid_model_output_is_silent(content):
    class Provider:
        async def generate(self, messages):
            assert '当前人格' in messages[0].content
            return ModelResponse(content=content)
    result = await ModelDecision(Provider(), '朝汐人格').decide([candidate()], NOW, PolicyState())
    assert result.action == 'silent'


async def test_model_failure_is_silent():
    class Provider:
        async def generate(self, messages):
            raise RuntimeError('offline')
    assert (await ModelDecision(Provider(), '').decide([candidate()], NOW, PolicyState())).action == 'silent'


async def test_heartbeat_runs_while_model_waits_and_shutdown_cancels():
    h, worker, _ = setup()
    await h.buffer.add(candidate())
    started = asyncio.Event()
    class Slow:
        async def decide(self, *args):
            started.set()
            await asyncio.Event().wait()
    worker.decision = Slow()
    task = asyncio.create_task(worker.tick(NOW))
    await started.wait()
    await h.tick(NOW)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    loop = asyncio.create_task(h.run())
    await asyncio.sleep(.01)
    loop.cancel()
    with pytest.raises(asyncio.CancelledError):
        await loop
    assert h.metrics.snapshot()['counters']['proactive.heartbeat'] >= 2


async def test_quiet_changed_during_model_request_blocks_popup():
    h, worker, _ = setup()
    class ChangesQuiet:
        async def decide(self, *args):
            h.state.quiet_until = NOW + timedelta(hours=1)
            return Decision(action='speak', content='稍作休息')
    worker.decision = ChangesQuiet()
    await h.buffer.add(candidate())
    assert not await worker.tick(NOW)
    assert not await h.runtime.store.list_deliveries()


async def test_natural_checkin_requires_context_activity_and_is_daily_deduped():
    h, worker, model = setup()
    h.started_at = NOW - timedelta(hours=4)
    h.state.last_interaction_at = h.started_at
    class Sensor:
        focus_active = False
        healthy = True
        context = '今天完成了两个任务'
        async def collect(self, now):
            return []
    h.sensors = [Sensor()]
    h.active = lambda: False
    await h.tick(NOW)
    assert not await h.runtime.store.pending_events()
    h.active = lambda: True
    await h.tick(NOW)
    await h.tick(NOW)
    assert len(await h.runtime.store.pending_events()) == 1
    await worker.tick(NOW)
    await h.tick(NOW + timedelta(hours=4))
    await worker.tick(NOW + timedelta(hours=4))
    assert len(model.calls) == 1

async def test_activation_context_is_persisted_across_restart(tmp_path):
    from zhaoxi.session.sqlite import SQLiteSessionStore
    h, worker, _ = setup()
    await h.buffer.add(candidate())
    delivery = (await worker.tick(NOW))[0]
    sessions = SQLiteSessionStore(tmp_path / 'sessions.db')
    session = await sessions.create()
    agent = SimpleNamespace(proactive=h.runtime, conversation=session.conversation,
                            session_store=sessions, session_record=session)
    await InterfaceGateway(agent).activate_delivery(delivery.delivery_id)
    restored = await SQLiteSessionStore(tmp_path / 'sessions.db').get(session.id)
    assert '100 分钟' in restored.conversation.messages[-1].background
    assert restored.conversation.messages[-1].content == delivery.content
    assert restored.conversation.messages[-1].delivery_id == delivery.delivery_id


async def test_pending_batch_survives_restart(tmp_path):
    path = tmp_path / 'proactive.db'
    h, _, _ = setup(SQLiteProactiveStore(path))
    await h.buffer.add(candidate())
    restored, worker, model = setup(SQLiteProactiveStore(path))
    assert len(await worker.tick(NOW)) == 1
    assert len(model.calls) == 1


async def test_reminder_in_same_batch_starts_cooldown_before_llm():
    h, worker, model = setup()
    await h.buffer.add(candidate())
    await h.runtime.store.save_schedule(Schedule(event_type='reminder.due', kind=ScheduleKind.ONCE,
                                                next_fire_at=NOW, payload={'text': '喝水'}))
    await h.tick(NOW)
    result = await worker.tick(NOW)
    assert len(result) == 1 and not model.calls


def test_activation_api_rejects_unknown_and_hides_raw_payload():
    from fastapi.testclient import TestClient
    from zhaoxi.web.app import create_app
    from zhaoxi.proactive.models import Delivery
    h, _, _ = setup()
    d = Delivery(event_id='e', subscription_id='s', priority=Priority.INFO, content='完成啦',
                 relevant_payload={'summary': '完成任务', 'internal': 'private'})
    asyncio.run(h.runtime.sink.deliver(d, NOW))
    agent = SimpleNamespace(proactive=h.runtime, conversation=Conversation())
    client = TestClient(create_app(agent=agent, settings=h.settings, api_token='local-secret'))
    assert client.post(f'/api/proactive/{d.delivery_id}/activate').status_code == 401
    headers = {'X-Zhaoxi-Token': 'local-secret'}
    assert client.post('/api/proactive/missing/activate', headers=headers).status_code == 404
    assert client.post(f'/api/proactive/{d.delivery_id}/activate', headers=headers).status_code == 200
    data = client.get('/api/proactive', headers=headers).json()
    assert data['deliveries'][0]['status'] == 'acknowledged'
    assert 'relevant_payload' not in data['deliveries'][0]
    assert 'private' not in str(client.get('/api/session', headers=headers).json())

async def test_focus_finishing_during_decision_cancels_stale_message():
    h, worker, _ = setup()
    from zhaoxi.sdk import StateSignal
    class Signals:
        active = True
        async def collect_signals(self, now):
            return [StateSignal(type='attention.focus', value='active' if self.active else 'inactive',
                                source='test', observed_at=now, expires_at=now + timedelta(minutes=2))]
    signals = Signals()
    h.signal_providers = [signals]
    h.state.interaction.observe_signals(await signals.collect_signals(NOW), NOW)
    h.focus_active = True
    e = candidate()
    e.payload['focus_id'] = 'f'
    await h.buffer.add(e)
    class FocusEnded:
        async def decide(self, *args):
            signals.active = False
            return Decision(action='speak', content='该休息了')
    worker.decision = FocusEnded()
    assert not await worker.tick(NOW)
    assert not await h.runtime.store.list_deliveries()
