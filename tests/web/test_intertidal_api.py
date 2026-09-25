import asyncio
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from zhaoxi.config.settings import Settings
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.models.base import ModelProvider
from zhaoxi.models.types import ModelResponse
from zhaoxi.proactive.decision import ModelDecision
from zhaoxi.proactive.models import Delivery, ProactiveEvent
from zhaoxi.proactive.notifications import InboxNotificationSink
from zhaoxi.proactive.policy import InterruptPolicy, PolicyState
from zhaoxi.proactive.runtime import ProactiveRuntime
from zhaoxi.proactive.store import InMemoryProactiveStore
from zhaoxi.session.sqlite import SQLiteSessionStore
from zhaoxi.tools.registry import ToolRegistry
from zhaoxi.web.app import create_app


class Provider(ModelProvider):
    calls = 0
    async def generate(self, messages, tools=None, **kwargs):
        self.calls += 1
        return ModelResponse(content='你好。')


def test_timeline_inspector_suggestions_and_clear_persist(tmp_path):
    provider = Provider()
    store = InMemoryProactiveStore()
    state = PolicyState()
    agent = ZhaoxiAgent(provider=provider, registry=ToolRegistry(), context_builder=ContextBuilder('朝汐'),
                        proactive=ProactiveRuntime(store, InboxNotificationSink(store), InterruptPolicy()),
                        proactive_state=state)
    sessions = SQLiteSessionStore(tmp_path / 'session.db')
    session = asyncio.run(sessions.create())
    agent.conversation = session.conversation
    agent.session_record, agent.session_store = session, sessions
    delivery = Delivery(delivery_id='test', event_id='test', subscription_id='test', priority='notice',
                        content='休息一下吧。', relevant_payload={'summary': '仅供模型参考的背景'})
    asyncio.run(agent.proactive.sink.deliver(delivery, datetime.now(UTC)))
    with TestClient(create_app(agent=agent, settings=Settings(_env_file=None), api_token='test-token')) as client:
        client.headers['X-Zhaoxi-Token'] = 'test-token'
        session_payload = client.get('/api/session').json()
        assert session_payload['timezone'] == 'Asia/Shanghai'
        first = session_payload['messages']
        assert len(first) == 1 and first[0]['content'] == delivery.content
        assert first[0]['timestamp'] == delivery.delivered_at.isoformat()
        assert 'background' not in first[0]
        assert client.post('/api/proactive/test/activate').status_code == 200
        assert client.get('/api/session').json()['messages'] == first
        assert client.get('/api/proactive/test/inspect').json()['relevant_payload']['summary'] == '仅供模型参考的背景'
        assert client.get('/api/proactive/missing/inspect').status_code == 404
        assert client.get('/api/suggestions').status_code == 404
        assert provider.calls == 0
        assert client.get('/api/diagnostics').json()['presence']['interaction_state'] == 'ACTIVE'
        assert client.post('/api/debug/presence', json={'state': 'ACTIVE'}).json()['debug_forced_state'] == 'ACTIVE'
        forced = client.post('/api/debug/presence', json={'state': 'SEMI_ACTIVE'})
        assert forced.status_code == 200
        assert forced.json()['interaction_state'] == 'SEMI_ACTIVE'
        assert client.get('/api/diagnostics').json()['presence']['debug_forced_state'] == 'SEMI_ACTIVE'
        assert client.post('/api/debug/presence', json={'state': 'AWAY'}).json()['interaction_state'] == 'AWAY'
        assert client.get('/api/diagnostics').json()['presence']['interaction_state'] == 'AWAY'
        assert client.post('/api/debug/presence', json={'state': None}).json()['debug_forced_state'] is None
        assert client.get('/favicon.ico').content[:4] == b'\x00\x00\x01\x00'
        client.delete('/api/session')
        assert client.get('/api/session').json()['messages'] == []
    assert asyncio.run(sessions.get(session.id)).conversation.messages == []


async def test_proactive_decision_serializes_presence_dates():
    class DecisionProvider(ModelProvider):
        calls = 0
        async def generate(self, messages, tools=None, **kwargs):
            import json
            self.calls += 1
            payload = json.loads(messages[-1].content)
            assert payload['interaction_state']['interaction_state'] == 'ACTIVE'
            assert payload['interaction_state']['last_user_interaction_at']
            return ModelResponse(content='{"action":"speak","content":"歇会儿吧。"}')
    provider = DecisionProvider()
    state = PolicyState()
    now = datetime.now(UTC)
    state.interaction.interact(now)
    result = await ModelDecision(provider, '朝汐').decide([ProactiveEvent(event_type='test', source='test')], now, state)
    assert result.action == 'speak' and provider.calls == 1
