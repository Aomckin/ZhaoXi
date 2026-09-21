import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from zhaoxi.core import attachments
from zhaoxi.core.agent import ZhaoxiAgent, AgentResponse
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.core.message import Message, Role
from zhaoxi.models.openai_compatible import OpenAICompatibleProvider
from zhaoxi.session.base import Session
from zhaoxi.session.sqlite import SQLiteSessionStore
from zhaoxi.web.app import ChatRequest, create_app

PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9S8AAAAASUVORK5CYII='


def test_image_validation_and_protective_limits(monkeypatch):
    assert attachments.MAX_IMAGE_BYTES == 100 * 1024 * 1024
    assert len(ChatRequest(images=[PNG] * 20).images) == 20
    with pytest.raises(ValidationError):
        ChatRequest(images=[PNG] * 21)
    for value in ['https://example.test/a.png', 'data:image/svg+xml;base64,AAAA',
                  'data:image/png;base64,!!!!', 'data:image/png;base64,YWJj']:
        with pytest.raises(ValidationError):
            ChatRequest(images=[value])
    monkeypatch.setattr(attachments, 'MAX_IMAGE_BYTES', 8)
    with pytest.raises(ValidationError):
        ChatRequest(images=[PNG])


async def test_provider_receives_image_parts_and_text():
    async def handler(request):
        content = json.loads(request.content)['messages'][0]['content']
        assert content == [{'type': 'text', 'text': '看图'},
                           {'type': 'image_url', 'image_url': {'url': PNG}}]
        return httpx.Response(200, json={'choices': [{'message': {'content': '看到了'}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(base_url='https://example.test', api_key='test', model='vision', client=client)
        result = await provider.generate([Message(role=Role.USER, content='看图', images=[PNG])])
    assert result.content == '看到了'
    assert Message(role=Role.USER, content='文字').to_provider_dict()['content'] == '文字'


def test_images_survive_session_storage_and_clear(tmp_path):
    store = SQLiteSessionStore(tmp_path / 'session.db')
    session = Session()
    session.conversation.add_user('看图', images=[PNG])
    store.save_sync(session)
    loaded = store.get_sync(session.id)
    assert loaded.conversation.messages[0].images == [PNG]
    loaded.conversation.clear()
    store.save_sync(loaded)
    assert store.get_sync(session.id).conversation.messages == []


def test_http_image_only_reaches_agent_and_history():
    class Agent:
        def __init__(self):
            self.conversation = Conversation()
            self.proactive = self.proactive_scheduler = self.proactive_state = None
        async def run_natural(self, text, *, images=None):
            self.conversation.add_user(text, images=images)
            return AgentResponse(content='看到了', request_id='image-test', steps=1)
    agent = Agent()
    with TestClient(create_app(agent=agent)) as client:
        response = client.post('/api/chat', json={'images': [PNG]})
        assert response.status_code == 200, response.text
        assert client.get('/api/session').json()['messages'][0]['images'] == [PNG]
        assert client.post('/api/chat', json={'images': ['bad']}).status_code == 422
        assert client.post('/api/chat', json={}).status_code == 422


async def test_agent_attaches_images_before_model_loop():
    agent = ZhaoxiAgent.__new__(ZhaoxiAgent)
    agent.conversation = Conversation()
    agent.context_builder = ContextBuilder('test')
    agent.timeout_seconds = 5
    async def loop(*args, **kwargs):
        assert agent.context_builder.build(agent.conversation)[-1].images == [PNG]
        return AgentResponse(content='看到了', request_id='test', steps=1)
    agent._run_loop = loop
    await agent.run('看图', images=[PNG])


async def test_image_turn_keeps_cognitive_postprocessing_and_uses_vision_loop():
    from zhaoxi.cognitive.coordinator import CognitiveCoordinator
    agent = SimpleNamespace(run=AsyncMock(return_value=AgentResponse(content='看到了', request_id='test', steps=1)))
    router = SimpleNamespace(route=AsyncMock())
    from zhaoxi.cognitive.memory_decision import MemoryAction
    memory = SimpleNamespace(process=AsyncMock(return_value=SimpleNamespace(action=MemoryAction.IGNORE)))
    coordinator = CognitiveCoordinator(agent=agent, router=router, auto_memory=memory)
    await coordinator.run('看图', images=[PNG])
    agent.run.assert_awaited_once_with(
        '看图', require_tool_call=False, required_tool=None, images=[PNG]
    )
    router.route.assert_not_awaited()
    memory.process.assert_awaited_once_with('看图', '看到了')
