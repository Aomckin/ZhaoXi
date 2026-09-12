"""Ordinary conversation consumes desktop observations without extra LLM work."""
import json
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from conftest import FakeProvider
from zhaoxi.config.settings import Settings
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.desktop.activity import DesktopActivity, ActivityInference
from zhaoxi.desktop.presence import DesktopSnapshot
from zhaoxi.models.types import ModelResponse
from zhaoxi.proactive.interaction import Interaction
from zhaoxi.session.sqlite import SQLiteSessionStore
from zhaoxi.tools.registry import ToolRegistry


def setup(age=0, inference=False):
    now = datetime.now(UTC)
    activity = DesktopActivity(Settings(_env_file=None))
    activity.update(DesktopSnapshot(foreground_process='Code.exe',
        foreground_title='memory_decision.py - ZhaoXi', foreground_window=1), now-timedelta(seconds=age))
    activity.context.input_shape.keyboard_rate_1m = 80
    if inference:
        activity.inference = ActivityInference(primary_activity='正在修改 Zhaoxi 代码', confidence=.88,
            activity_mode='text_production')
        activity.inferred_at = now
    interaction = Interaction()
    interaction.desktop_activity = activity
    context = ContextBuilder('朝汐人格')
    context.interaction = interaction
    return context, activity


def desktop_data(messages):
    section = messages[0].content.split('[Desktop Activity]\n')[1].split('\n[/Desktop Activity]')[0]
    return json.loads(section[section.index('{'):])


@pytest.mark.parametrize('inference', [False, True])
async def test_direct_receives_activity_abstraction_and_optional_cached_inference(inference):
    context, activity = setup(inference=inference)
    provider = FakeProvider([ModelResponse(content='能看到，焦点在 VS Code。')])
    agent = ZhaoxiAgent(provider=provider, registry=ToolRegistry(), context_builder=context)
    result = await agent.run_direct('你现在能看到我在哪个软件吗？')
    assert result.content == '能看到，焦点在 VS Code。'
    assert len(provider.calls) == 1 and provider.tool_schemas == [None]
    data = desktop_data(provider.calls[0])
    assert data['available'] and not data['stale']
    assert data['foreground_process'] == 'Code.exe'
    assert data['foreground_title'] == 'memory_decision.py - ZhaoXi'
    assert data['activity_state']['recently_operated']
    assert data['activity_state']['primary_source'] == '键盘'
    assert 'keyboard_rate_1m' not in data and 'mouse_rate_1m' not in data
    assert 'busy_evidence' not in data
    assert data['activity_confidence'] == (.88 if inference else None)
    assert data['activity_summary'] == ('正在修改 Zhaoxi 代码' if inference else None)
    assert data['activity_mode'] == ('text_production' if inference else 'unknown')
    assert activity.last_attempt is None


def test_stale_is_last_observation_not_live():
    context, _ = setup(age=60)
    data = desktop_data(context.build(Conversation()))
    assert data['available'] and data['stale'] and data['age_seconds'] >= 60
    assert data['foreground_process'] == 'Code.exe'


@pytest.mark.parametrize('state', ['missing', 'locked', 'disabled'])
def test_unavailable_does_not_leak_previous_title(state):
    context, activity = setup()
    if state == 'missing':
        context.interaction.desktop_activity = None
    elif state == 'disabled':
        activity.settings.desktop_activity_enabled = False
    else:
        activity.update(DesktopSnapshot(locked=True), datetime.now(UTC))
    data = desktop_data(context.build(Conversation()))
    assert not data['available']
    assert 'foreground_title' not in data


def test_expired_inference_omitted_but_raw_context_present():
    context, activity = setup(inference=True)
    activity.inferred_at = datetime.now(UTC)-timedelta(minutes=5)
    data = desktop_data(context.build(Conversation()))
    assert data['activity_summary'] is None and data['foreground_process'] == 'Code.exe'


async def test_runtime_only_no_title_in_session_logs_or_memory_input(tmp_path, caplog):
    from zhaoxi.cognitive.coordinator import CognitiveCoordinator
    from zhaoxi.cognitive.router import CognitiveRoute, RouteDecision
    context, activity = setup()
    provider = FakeProvider([ModelResponse(content='能看到，焦点在 VS Code。')])
    agent = ZhaoxiAgent(provider=provider, registry=ToolRegistry(), context_builder=context)
    memory_inputs = []
    class Router:
        async def route(self, *args, **kwargs):
            return RouteDecision(route=CognitiveRoute.DIRECT)
    class Memory:
        async def process(self, *args):
            memory_inputs.append(args)
            return SimpleNamespace(action=SimpleNamespace(value='ignore'))
    agent.cognitive = CognitiveCoordinator(agent=agent, router=Router(), auto_memory=Memory())
    caplog.set_level(logging.INFO)
    await agent.run_natural('你能看到前台吗？')
    store = SQLiteSessionStore(tmp_path/'session.db')
    session = await store.create()
    session.conversation = agent.conversation
    await store.save(session)
    restored = await store.get(session.id)
    title = activity.context.foreground_title
    assert title not in json.dumps([m.model_dump(mode='json') for m in restored.conversation.messages], ensure_ascii=False)
    assert title not in str(memory_inputs) and title not in caplog.text
    assert title not in json.dumps(activity.diagnostics(), default=str)
    assert title not in json.dumps(context.interaction.diagnostics(datetime.now(UTC)), default=str)
    assert len(provider.calls) == 1


async def test_tool_loop_also_uses_runtime_snapshot():
    context, _ = setup()
    provider = FakeProvider([ModelResponse(content='当前是 VS Code。')])
    agent = ZhaoxiAgent(provider=provider, registry=ToolRegistry(), context_builder=context)
    await agent.run('看一下当前软件')
    assert desktop_data(provider.calls[0])['foreground_process'] == 'Code.exe'
