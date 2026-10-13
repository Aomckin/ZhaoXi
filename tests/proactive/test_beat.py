import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from conftest import FakeProvider
from zhaoxi.config.settings import Settings
from zhaoxi.core.conversation import Conversation
from zhaoxi.models.types import ModelResponse
from zhaoxi.proactive.beat import ConversationBeatLoop
from zhaoxi.proactive.decision import ModelDecision
from zhaoxi.proactive.heartbeat import TidalHeartbeat
from zhaoxi.proactive.interaction import InteractionState
from zhaoxi.proactive.models import Delivery, Priority, ProactiveEvent
from zhaoxi.proactive.notifications import InboxNotificationSink
from zhaoxi.proactive.policy import PolicyState, InterruptPolicy
from zhaoxi.proactive.runtime import ProactiveRuntime
from zhaoxi.proactive.scheduler import Scheduler
from zhaoxi.proactive.store import InMemoryProactiveStore
from zhaoxi.proactive.worker import DecisionWorker
from zhaoxi.reliability.metrics import MetricRegistry
from zhaoxi.sdk import StateSignal

NOW = datetime(2026, 9, 9, 4, tzinfo=UTC)


def setup(action='COMMENT'):
    settings = Settings(_env_file=None)
    state = PolicyState()
    conversation = Conversation()
    conversation.add_user('认可你是我的犬娘了。')
    conversation.add_assistant('这句话让我鼻子有点酸。')
    loop = ConversationBeatLoop(settings, state.interaction, conversation)
    state.interaction.interact(NOW)
    loop.note_user_message(conversation.messages[0].content, NOW)
    loop.note_assistant(NOW)
    provider = FakeProvider([ModelResponse(content='{"action":"'+action+'","content":"女仆长的位置我可不会让。","reason":"callback","confidence":0.82}')])
    store = InMemoryProactiveStore()
    runtime = ProactiveRuntime(store, InboxNotificationSink(store), InterruptPolicy())
    heartbeat = TidalHeartbeat(runtime, Scheduler(store), state, settings, MetricRegistry())
    heartbeat.continuation = loop
    worker = DecisionWorker(heartbeat, ModelDecision(provider, '你是朝汐。', conversation=conversation))
    return loop, worker, provider, state, store


async def test_non_open_thread_beat_sends_without_world_event():
    loop, worker, provider, state, store = setup()
    assert loop.open_thread is None
    assert not await worker.tick(NOW+timedelta(seconds=179))
    assert not provider.calls
    result = await worker.tick(NOW+timedelta(seconds=180))
    assert len(result) == 1 and result[0].event_type == 'conversation.beat'
    assert len(provider.calls) == 1 and provider.tool_schemas == [None]
    assert loop.session.initiative_budget == 1
    context = json.loads(provider.calls[0][1].content)
    assert 'recent_conversation' in context
    assert context['current_time'] == '2026-09-09T12:03:00+08:00'
    assert context['timezone'] == 'Asia/Shanghai'
    assert loop.session.last_beat_result == 'COMMENT'


async def test_silent_consumes_cooldown_not_budget():
    loop, worker, provider, state, store = setup('SILENT')
    assert not await worker.tick(NOW+timedelta(minutes=3))
    assert loop.session.initiative_budget == 2
    assert not await worker.tick(NOW+timedelta(minutes=4))
    assert len(provider.calls) == 1
    assert loop.diagnostics(NOW+timedelta(minutes=4))['last_silent_reason'] == 'model_silent'


async def test_busy_then_stopped_input():
    loop, worker, provider, state, store = setup()
    now = NOW+timedelta(minutes=3)
    state.interaction.observe_signals([StateSignal(type='desktop.input_active', value=True,
        source='desktop', observed_at=now, expires_at=now+timedelta(seconds=15))], now)
    assert await worker.tick(now)
    assert provider.calls and loop.last_trace['interruptibility'] == 'LOW'
    assert loop.last_trace['gate_passed'] and loop.last_trace['llm_confidence'] == .82


async def test_extreme_input_defers_but_falling_trend_restores_beat():
    from zhaoxi.desktop.activity import DesktopActivity, InputShape
    from zhaoxi.desktop.presence import DesktopSnapshot
    loop, worker, provider, state, store = setup()
    now = NOW+timedelta(minutes=3)
    activity = DesktopActivity(loop.settings)
    shape = InputShape(keyboard_rate_1m=500, keyboard_rate_5m=500, keyboard_idle_seconds=1)
    activity.counters.shape = lambda idle: shape
    state.interaction.desktop_activity = activity
    activity.update(DesktopSnapshot(), now)
    assert not await worker.tick(now)
    assert not provider.calls and loop.last_trace['desktop_busy']
    assert loop.last_trace['gate_reason'] == 'desktop_busy'
    shape.keyboard_rate_1m = 150
    activity.update(DesktopSnapshot(), now+timedelta(seconds=2))
    assert await worker.tick(now+timedelta(seconds=2))
    assert loop.last_trace['delivered'] and not loop.last_trace['desktop_busy']


async def test_fullscreen_low_can_reach_model_but_blocked_cannot():
    from zhaoxi.desktop.presence import DesktopSnapshot
    loop, worker, provider, state, store = setup()
    now = NOW+timedelta(minutes=3)
    state.interaction.observe(DesktopSnapshot(fullscreen=True), now)
    assert await worker.tick(now)
    assert loop.last_trace['interruptibility'] == 'LOW'
    loop, worker, provider, state, store = setup()
    state.interaction.observe(DesktopSnapshot(locked=True), now)
    assert not await worker.tick(now) and not provider.calls


async def test_budget_reply_refill_and_no_self_renewal():
    loop, worker, provider, state, store = setup()
    started = loop.session.started_at
    await worker.tick(NOW+timedelta(minutes=3))
    state.interaction.interact(NOW+timedelta(minutes=4))
    loop.note_user_message('那当然，女仆长还是你。', NOW+timedelta(minutes=4))
    assert loop.session.started_at == started and loop.session.initiative_budget == 2
    loop.note_user_message('还有呢', NOW+timedelta(minutes=4, seconds=1))
    assert loop.session.initiative_budget == 2
    assert await worker.tick(NOW+timedelta(minutes=8, seconds=1))
    assert await worker.tick(NOW+timedelta(minutes=13, seconds=2))
    assert not await worker.tick(NOW+timedelta(minutes=19))
    assert loop.session.last_silent_reason == 'budget_exhausted'
    await worker.tick(NOW+timedelta(minutes=25))
    assert state.interaction.state == InteractionState.SEMI_ACTIVE and loop.session is None


@pytest.mark.parametrize('kind', ['quiet', 'busy', 'permission', 'disabled'])
async def test_pre_model_gates(kind):
    loop, worker, provider, state, store = setup()
    if kind == 'quiet': state.quiet_until = NOW+timedelta(hours=1)
    if kind == 'busy': state.interacting = True
    if kind == 'permission': loop.pending_work = lambda: True
    if kind == 'disabled': state.enabled = False
    assert not await worker.tick(NOW+timedelta(minutes=3))
    assert not provider.calls


async def test_user_reply_during_model_discards_old_beat():
    loop, worker, provider, state, store = setup()
    async def generate(*args, **kwargs):
        state.interaction.interact(NOW+timedelta(minutes=3, seconds=1))
        loop.note_user_message('我又回来了', NOW+timedelta(minutes=3, seconds=1))
        return ModelResponse(content='{"action":"COMMENT","content":"旧话题","reason":"reaction","confidence":0.8}')
    provider.generate = generate
    assert not await worker.tick(NOW+timedelta(minutes=3))
    assert loop.session.initiative_budget == 2


async def test_recent_ordinary_delivery_blocks_beat():
    loop, worker, provider, state, store = setup()
    await worker.heartbeat.runtime.sink.deliver(Delivery(event_id='e', subscription_id='s',
        priority=Priority.NOTICE, content='普通主动'), NOW+timedelta(minutes=2))
    assert not await worker.tick(NOW+timedelta(minutes=3))
    assert not provider.calls and loop.session.last_silent_reason == 'recent_proactive'


async def test_open_thread_is_only_a_reason():
    loop, worker, provider, state, store = setup()
    loop.note_user_message('我去试一下刚才的修复', NOW)
    await worker.tick(NOW+timedelta(minutes=3))
    assert 'open_thread' in provider.calls[0][1].content

async def test_deferred_ordinary_cannot_bypass_beat_cooldown():
    from zhaoxi.proactive.models import DeliveryStatus
    loop, worker, provider, state, store = setup()
    assert await worker.tick(NOW+timedelta(minutes=3))
    event = ProactiveEvent(event_type='world.changed', source='test', dedupe_key='deferred', occurred_at=NOW)
    await store.add_event(event)
    pending = Delivery(event_id=event.event_id, subscription_id='s', event_type=event.event_type,
        priority=Priority.NOTICE, content='不要紧跟着发送', status=DeliveryStatus.DEFERRED,
        available_at=NOW+timedelta(minutes=4))
    await store.save_delivery(pending)
    assert not await worker.tick(NOW+timedelta(minutes=4))
    assert (await store.get_delivery(pending.delivery_id)).status == DeliveryStatus.DEFERRED


async def test_model_failure_is_visible_and_bounded():
    loop, worker, provider, state, store = setup()
    provider.responses.clear()
    provider.responses.append(ModelResponse(content='not json'))
    assert not await worker.tick(NOW+timedelta(minutes=3))
    assert loop.session.last_silent_reason == 'invalid_json'
    assert not await worker.tick(NOW+timedelta(minutes=4))
    assert len(provider.calls) == 1


def test_inspect_authenticated_and_diagnostics_have_no_model_content():
    from fastapi.testclient import TestClient
    from zhaoxi.web.app import create_app
    loop, worker, provider, state, store = setup()
    agent = SimpleNamespace(conversation=loop.conversation, proactive_state=state,
        proactive_worker=worker)
    client = TestClient(create_app(agent=agent, settings=loop.settings, api_token='secret'))
    assert client.get('/api/proactive/active/inspect').status_code == 401
    response = client.get('/api/proactive/active/inspect', headers={'X-Zhaoxi-Token':'secret'})
    assert response.status_code == 200
    assert 'session' in response.json()

async def test_night_suppresses_model():
    loop, worker, provider, state, store = setup()
    late = NOW.replace(hour=16)
    state.interaction.interact(late)
    loop.note_user_message('普通聊天', late)
    assert not await worker.tick(late+timedelta(minutes=3))
    assert not provider.calls and loop.session.last_silent_reason == 'night_mode'


async def test_new_active_window_resets_budget_and_session():
    loop, worker, provider, state, store = setup()
    await worker.tick(NOW+timedelta(minutes=3))
    state.interaction.interact(NOW+timedelta(minutes=25))
    loop.note_user_message('开启新的对话', NOW+timedelta(minutes=25))
    assert loop.session.started_at == NOW+timedelta(minutes=25)
    assert loop.session.initiative_budget == 2 and loop.session.beat_count == 0


async def test_busy_during_model_is_checked_before_send():
    loop, worker, provider, state, store = setup()
    async def generate(*args, **kwargs):
        state.interacting = True
        return ModelResponse(content='{"action":"COMMENT","content":"旧回复","reason":"reaction","confidence":0.8}')
    provider.generate = generate
    assert not await worker.tick(NOW+timedelta(minutes=3))
    assert loop.session.last_silent_reason == 'request_busy'
    assert loop.session.initiative_budget == 2

async def test_trace_distinguishes_gate_from_model_silent_and_delivery():
    loop, worker, provider, state, store = setup('SILENT')
    state.interacting = True
    await worker.tick(NOW+timedelta(minutes=3))
    trace = loop.last_trace
    assert trace['scheduled'] and trace['gated'] and not trace['llm_called']
    assert trace['gate_reason'] == 'request_busy' and trace['llm_action'] is None
    state.interacting = False
    await worker.tick(NOW+timedelta(minutes=3, seconds=1))
    assert loop.last_trace['llm_called'] and loop.last_trace['llm_action'] == 'SILENT'
    assert not loop.last_trace['gated'] and not loop.last_trace['delivered']
    assert loop.last_trace['suppression_reason'] == 'model_silent'


async def test_successful_beat_increments_both_delivery_counters():
    loop, worker, provider, state, store = setup()
    await worker.tick(NOW+timedelta(minutes=3))
    assert loop.last_trace['delivered']
    counters = worker.heartbeat.metrics.snapshot()['counters']
    assert counters['proactive.deliveries'] == 1 and counters['proactive.beat_deliveries'] == 1

@pytest.mark.parametrize('content,finish,error', [
    ('', None, 'empty_response'),
    ('not json', None, 'invalid_json'),
    ('{"action":"UNKNOWN"}', None, 'invalid_schema'),
    ('{"action":"COMMENT","content":" "}', None, 'empty_beat_content'),
    ('{"action":"SILENT"}', 'length', 'response_truncated'),
])
async def test_model_response_failures_have_safe_specific_diagnostics(content, finish, error):
    loop, worker, provider, state, store = setup()
    provider.responses.clear()
    provider.responses.append(ModelResponse(content=content, finish_reason=finish))
    assert not await worker.tick(NOW+timedelta(minutes=3))
    trace = loop.last_trace
    assert trace['model_error'] == error and trace['llm_action'] is None
    assert trace['model_diagnostics']['content_length'] == len(content)
    assert 'content' not in trace['model_diagnostics']
    assert loop.session.initiative_budget == 2


async def test_fenced_json_is_validated_and_json_mode_requested():
    loop, worker, provider, state, store = setup()
    async def generate(messages, **kwargs):
        assert kwargs['response_format'] == {'type': 'json_object'}
        return ModelResponse(content='```json\n{"action":"COMMENT","content":"hello","confidence":0.8}\n```')
    provider.generate = generate
    assert await worker.tick(NOW+timedelta(minutes=3))
    assert loop.last_trace['model_diagnostics']['json_fence_removed']


@pytest.mark.parametrize('error,expected', [(TimeoutError(), 'model_timeout'), (RuntimeError('private'), 'model_request_failed')])
async def test_request_failure_is_distinct_from_response_validation(error, expected):
    loop, worker, provider, state, store = setup()
    async def generate(*args, **kwargs):
        raise error
    provider.generate = generate
    assert not await worker.tick(NOW+timedelta(minutes=3))
    assert loop.last_trace['model_error'] == expected
    assert loop.last_trace['model_diagnostics'] == {'stage': 'request', 'exception_type': type(error).__name__}

async def test_beat_reports_post_response_token_budget_error():
    from zhaoxi.models.resilient import ResilientProvider
    loop, worker, provider, state, store = setup()
    provider.responses[0].usage = {'total_tokens': 32001}
    worker.decision.provider = ResilientProvider([provider])
    assert not await worker.tick(NOW+timedelta(minutes=3))
    assert loop.last_trace['model_diagnostics']['provider_error_code'] == 'provider_token_budget_exhausted'
    assert loop.last_trace['llm_action'] is None

async def test_poke_runs_one_beat_without_waiting_and_preserves_request_gate():
    loop, worker, provider, state, store = setup()
    assert await worker.poke()
    assert len(provider.calls) == 1
    assert loop.last_trace['forced'] and loop.last_trace['delivered']
    state.interacting = True
    assert not await worker.poke()
    assert len(provider.calls) == 1
    assert loop.last_trace['gate_reason'] == 'request_busy'


async def test_beat_accepts_normal_context_above_old_token_budget():
    from zhaoxi.models.resilient import ResilientProvider
    loop, worker, provider, state, store = setup()
    provider.responses[0].usage = {'total_tokens': 24000}
    original = provider.generate
    async def generate(messages, tools=None, **kwargs):
        assert kwargs['max_tokens'] == 16000
        return await original(messages, tools, **kwargs)
    provider.generate = generate
    worker.decision.provider = ResilientProvider([provider])
    assert await worker.tick(NOW+timedelta(minutes=3))
    assert loop.last_trace['delivered'] and len(provider.calls) == 1



def image_stream(tmp_path, images):
    from zhaoxi.cognitive_stream import CognitiveIngress, ExperienceStream
    stream = ExperienceStream(tmp_path / 'experience.db')
    event = CognitiveIngress(stream).desktop('', images=images, channel='web')
    return stream, event


async def test_beat_receives_actual_historical_thumbnails_for_image_only_input(tmp_path, five_large_photos):
    import base64
    from io import BytesIO
    from PIL import Image
    loop, worker, provider, state, store = setup()
    stream, event = image_stream(tmp_path, list(five_large_photos))
    loop.experience_stream = stream
    assert await worker.tick(NOW + timedelta(minutes=3))
    context = json.loads(provider.calls[0][1].content)
    row = context['recent_conversation'][0]
    assert context['last_user_message'] == row['content'] == ''
    assert row['event_id'] == event.event_id and row['image_count'] == row['image_attached_count'] == 5
    assert row['image_indexes'] == [1, 2, 3, 4, 5] and row['actor_role'] == 'OWNER' and row['channel'] == 'web'
    assert 'data:image/' not in provider.calls[0][1].content
    reference = provider.calls[0][2]
    assert event.event_id in reference.content
    assert len(reference.images) == 5 and provider.tool_schemas == [None]
    for preview, original in zip(reference.images, five_large_photos):
        assert preview != original
        with Image.open(BytesIO(base64.b64decode(preview.split(',', 1)[1]))) as frame:
            assert max(frame.size) <= 512
    assert stream.get(event.event_id).content == ''
    assert [part.url for part in stream.get(event.event_id).parts] == list(five_large_photos)


async def test_beat_forwards_more_than_twenty_history_images_without_adding_count_cap(tmp_path):
    from zhaoxi.cognitive_stream import CognitiveIngress
    image = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9S8AAAAASUVORK5CYII='
    loop, worker, provider, state, store = setup()
    stream, first = image_stream(tmp_path, [image] * 20)
    second = CognitiveIngress(stream).desktop('', images=[image] * 10, channel='web')
    loop.experience_stream = stream
    assert await worker.tick(NOW + timedelta(minutes=3))
    references = provider.calls[0][2:]
    assert [len(message.images) for message in references] == [20, 10]
    assert first.event_id in references[0].content and second.event_id in references[1].content
    assert sum(len(message.images) for message in provider.calls[0]) == 30


async def test_beat_unavailable_image_is_marked_as_historical_unreadable(tmp_path):
    loop, worker, provider, state, store = setup()
    loop.experience_stream, event = image_stream(tmp_path, ['https://example.test/unavailable.jpg'])
    assert await worker.tick(NOW + timedelta(minutes=3))
    row = json.loads(provider.calls[0][1].content)['recent_conversation'][0]
    assert row['image_count'] == 1 and row['image_attached_count'] == 0 and row['image_indexes'] == []
    assert '不可用' in row['content']
    assert not any(message.images for message in provider.calls[0])
    assert 'https://example.test' not in provider.calls[0][1].content


@pytest.mark.parametrize('continuation', [False, True])
async def test_other_proactive_decisions_also_receive_historical_picture(tmp_path, continuation):
    from zhaoxi.cognitive_stream import AttentionRetriever
    loop, worker, provider, state, store = setup()
    image = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9S8AAAAASUVORK5CYII='
    stream, event = image_stream(tmp_path, [image])
    model = worker.decision
    model.attention_retriever = AttentionRetriever(stream)
    provider.responses[0] = ModelResponse(content='{"action":"speak","content":"看到之前的图了。"}')
    if continuation:
        result = await model.decide_continuation(SimpleNamespace(user_text='', summary='之前的图片'), NOW, state)
    else:
        result = await model.decide([], NOW, state)
    assert result.action == 'speak'
    row = json.loads(provider.calls[0][1].content)['recent_conversation'][0]
    assert row['event_id'] == event.event_id and row['content'] == '' and row['image_attached_count'] == 1
    assert len(provider.calls[0][2].images) == 1 and provider.tool_schemas == [None]


def test_proactive_picture_context_keeps_external_author_and_excludes_emoji():
    from zhaoxi.core.message import Message, Role
    from zhaoxi.core.image_thumbnails import ImageThumbnailCache
    from zhaoxi.proactive.vision import visual_history
    image = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9S8AAAAASUVORK5CYII='
    recent, attachments = visual_history([
        Message(role=Role.EXTERNAL, content='', images=[image], source='qq',
                metadata={'channel':'qq', 'actor_role':'THIRD_PARTY'}),
        Message(role=Role.ASSISTANT, content='', images=[image], source='emoji'),
    ], ImageThumbnailCache())
    assert recent[0]['actor_role'] == 'THIRD_PARTY' and recent[0]['source'] == 'qq'
    assert len(attachments) == 1 and 'THIRD_PARTY' in attachments[0].content
    assert 'image_count' not in recent[1]


async def test_image_only_user_reply_renews_beat_budget_without_fabricated_text():
    from zhaoxi.core.agent import AgentResponse
    from zhaoxi.interfaces import InterfaceGateway, UnifiedMessage
    loop, worker, provider, state, store = setup()
    assert await worker.tick(NOW + timedelta(minutes=3))
    assert loop.session.awaiting_reply and loop.session.initiative_budget == 1
    image = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9S8AAAAASUVORK5CYII='
    # Preserve the live ACTIVE session while using the gateway's actual clock.
    from unittest.mock import patch
    moment = NOW + timedelta(minutes=4)
    class Clock:
        @staticmethod
        def now(_timezone):
            return moment
    class Agent:
        conversation = Conversation()
        proactive_state = state
        conversation_continuation = loop
        async def run_natural(self, content, *, images):
            assert content == '' and images == [image]
            self.conversation.add_user(content, images=images)
            self.conversation.add_assistant('看到了')
            return AgentResponse(content='看到了', request_id='picture-reply', steps=1)
    with patch('zhaoxi.interfaces.gateway.datetime', Clock):
        await InterfaceGateway(Agent()).chat(UnifiedMessage(channel='web', content='', images=[image]))
    assert not loop.session.awaiting_reply and loop.session.initiative_budget == 2
    assert loop.session.last_user_at == moment and loop.open_thread is None


async def test_quiet_off_clears_infinite_signal_and_restores_automatic_beat():
    loop, worker, provider, state, store = setup()
    state.quiet_until = datetime.max.replace(tzinfo=UTC)
    await worker.heartbeat.tick(NOW)
    assert state.interaction.signals.resolve('interruptibility.manual', NOW).source == 'quiet_mode'
    state.quiet_until = None
    # No heartbeat needed between the tray action and a queued decision.
    assert await worker.tick(NOW + timedelta(minutes=3))
    assert loop.last_trace['delivered'] and len(provider.calls) == 1
    assert state.interaction.signals.resolve('interruptibility.manual', NOW) is None


async def test_heartbeat_clears_cancelled_quiet_without_removing_other_blocks():
    loop, worker, provider, state, store = setup()
    state.quiet_until = datetime.max.replace(tzinfo=UTC)
    await worker.heartbeat.tick(NOW)
    state.interaction.observe_signals([StateSignal(type='interruptibility.manual',
        value='blocked', source='other_provider', observed_at=NOW,
        expires_at=NOW + timedelta(hours=1))], NOW)
    state.quiet_until = None
    await worker.heartbeat.tick(NOW + timedelta(seconds=1))
    assert state.interaction.signals.resolve('interruptibility.manual', NOW).source == 'other_provider'
    assert not await worker.tick(NOW + timedelta(minutes=3))
    assert not provider.calls and loop.last_trace['gate_reason'] == 'manual_blocked'


async def test_forced_poke_bypasses_quiet_for_one_delivery_only():
    loop, worker, provider, state, store = setup()
    now = datetime.now(UTC)
    state.quiet_until = datetime.max.replace(tzinfo=UTC)
    await worker.heartbeat.tick(now)
    assert await worker.poke()
    assert len(provider.calls) == 1 and loop.last_trace['delivered']
    assert state.quiet_until == datetime.max.replace(tzinfo=UTC)
    assert state.interaction.signals.resolve('interruptibility.manual', now).source == 'quiet_mode'
    assert loop.gate(now + timedelta(minutes=3), state) == 'quiet_mode'


@pytest.mark.parametrize('block', ['locked', 'other_manual', 'busy', 'disabled'])
async def test_forced_poke_preserves_hard_blocks_even_in_quiet_mode(block):
    from zhaoxi.proactive.interaction import PresenceSnapshot
    loop, worker, provider, state, store = setup()
    now = datetime.now(UTC)
    state.quiet_until = datetime.max.replace(tzinfo=UTC)
    await worker.heartbeat.tick(now)
    reasons = {'locked': 'screen_locked', 'other_manual': 'manual_blocked',
               'busy': 'request_busy', 'disabled': 'proactive_disabled'}
    if block == 'locked':
        state.interaction.observe(PresenceSnapshot(locked=True), now)
    elif block == 'other_manual':
        state.interaction.observe_signals([StateSignal(type='interruptibility.manual',
            value='blocked', source='other_provider', observed_at=now,
            expires_at=now + timedelta(hours=1))], now)
    elif block == 'busy':
        state.interacting = True
    else:
        state.enabled = False
    assert not await worker.poke()
    assert not provider.calls and loop.last_trace['gate_reason'] == reasons[block]


async def test_locking_during_forced_model_call_suppresses_delivery():
    from zhaoxi.proactive.interaction import PresenceSnapshot
    loop, worker, provider, state, store = setup()
    async def generate(*args, **kwargs):
        state.interaction.observe(PresenceSnapshot(locked=True), datetime.now(UTC))
        return ModelResponse(content='{"action":"COMMENT","content":"must not deliver","reason":"reaction","confidence":0.8}')
    provider.generate = generate
    assert not await worker.poke()
    assert loop.last_trace['suppression_reason'] == 'conversation_changed'
    assert not await store.list_deliveries(10)
