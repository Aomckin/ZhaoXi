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
from zhaoxi.models.types import ModelResponse, ToolCall
from zhaoxi.tools.registry import ToolRegistry
from tools.lifehud_tool import LifeHudClient, LifeHudTool
from conftest import FakeProvider

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


async def test_current_message_image_reaches_lifehud_without_entering_tool_arguments():
    paths = []
    def handler(request):
        paths.append(request.url.path)
        if request.url.path == '/api/images':
            assert request.method == 'POST' and PNG.split(',', 1)[1].encode() not in request.content
            assert b'filename="attachment.png"' in request.content
            return httpx.Response(200, json={'path': '/uploads/hash.png'})
        if request.method == 'POST':
            assert json.loads(request.content)['images'] == ['/uploads/hash.png']
            return httpx.Response(201, json={'id': 'meal-1'})
        return httpx.Response(200, json={'id': 'meal-1', 'images': ['/uploads/hash.png']})
    client = LifeHudClient('http://lifehud.test', transport=httpx.MockTransport(handler), retry_backoff_seconds=0)
    tool = LifeHudTool(client)
    tool.default_confirm_write = False
    registry = ToolRegistry()
    registry.register(tool)
    call = ToolCall(id='call-1', name='lifehud', arguments={'operation': 'record', 'arguments': {
        'action': 'create', 'type': 'meal', 'description': '晚餐', 'images': ['<current-message-image>'],
    }})
    provider = FakeProvider([ModelResponse(tool_calls=[call]), ModelResponse(content='已经记下晚餐。')])
    agent = ZhaoxiAgent(provider=provider, registry=registry, context_builder=ContextBuilder('朝汐'), tool_router_mode='all')
    result = await agent.run('把这张晚餐照片记进 LifeHUD', images=[PNG])
    assert '已经记下' in result.content
    assert paths == ['/api/images', '/api/life/meals', '/api/life/meals/meal-1']
    assert call.arguments['arguments']['images'] == ['<current-message-image>']
    assert agent.conversation.messages[-2].role == Role.TOOL
    assert [len(message.images) for message in provider.calls[0] if message.role == Role.USER] == [1]
    assert [len(message.images) for message in provider.calls[1] if message.role == Role.USER] == [1]


async def test_lifehud_image_survives_write_confirmation():
    paths = []
    def handler(request):
        paths.append(request.url.path)
        if request.url.path == '/api/images':
            return httpx.Response(200, json={'path': '/uploads/hash.png'})
        if request.method == 'POST':
            return httpx.Response(201, json={'id': 'meal-1'})
        return httpx.Response(200, json={'id': 'meal-1', 'images': ['/uploads/hash.png']})
    registry = ToolRegistry()
    registry.register(LifeHudTool(LifeHudClient('http://lifehud.test', transport=httpx.MockTransport(handler))))
    call = ToolCall(id='call-1', name='lifehud', arguments={'operation': 'record', 'arguments': {
        'type': 'meal', 'images': ['<current-message-image>'],
    }})
    agent = ZhaoxiAgent(provider=FakeProvider([ModelResponse(tool_calls=[call]), ModelResponse(content='完成')]),
                        registry=registry, context_builder=ContextBuilder('朝汐'), tool_router_mode='all')
    waiting = await agent.run('把照片记到 LifeHUD', images=[PNG])
    assert waiting.permission_confirmation is not None and paths == []
    assert PNG not in str(waiting.permission_confirmation.request.arguments)
    result = await agent.approve_permission(waiting.permission_confirmation.confirmation_id)
    assert result.content == '完成'
    assert paths == ['/api/images', '/api/life/meals', '/api/life/meals/meal-1']

def test_live_timeline_keeps_current_image_in_tool_free_finalization(tmp_path):
    from zhaoxi.cognitive_stream import ExperienceStream, AttentionRetriever
    from zhaoxi.cognitive_stream.ingress import CognitiveIngress
    from zhaoxi.cognitive_stream.turn import CognitiveTurnContext, set_current_turn, reset_current_turn
    stream = ExperienceStream(tmp_path / "experience.db")
    ingress = CognitiveIngress(stream)
    conversation = Conversation()
    old = conversation.add_user("旧图片", images=[PNG])
    ingress.desktop("旧图片", message_id=old.message_id, images=[PNG], channel="web")
    current = conversation.add_user("请查看这些图片。", images=[PNG])
    trigger = ingress.desktop(current.content, message_id=current.message_id,
                              images=[PNG], channel="web")
    builder = ContextBuilder("人格")
    builder.attention_retriever = AttentionRetriever(stream)
    token = set_current_turn(CognitiveTurnContext(
        trigger_event=trigger, output_channel="web", images=(PNG,)))
    try:
        final = builder.build(conversation, output_channel="web",
            current_image_message_id=current.message_id,
            release_images=True, preserve_current_image=True)
    finally:
        reset_current_turn(token)
    assert sum(len(message.images) for message in final) == 1
    assert final[-1].images == [PNG]

async def test_image_only_request_is_one_vision_call_without_tools():
    from zhaoxi.cognitive.coordinator import CognitiveCoordinator
    provider = FakeProvider([ModelResponse(content="看到了这张图片。")])
    agent = ZhaoxiAgent(provider=provider, registry=ToolRegistry(),
                        context_builder=ContextBuilder("朝汐"))
    router = SimpleNamespace(route=AsyncMock())
    agent.cognitive = CognitiveCoordinator(agent=agent, router=router)
    reply = await agent.run_natural("请查看这些图片。", images=[PNG])
    assert "看到了" in reply.content
    assert len(provider.calls) == 1
    assert provider.tool_schemas == [None]
    assert [m.images for m in provider.calls[0] if m.role == Role.USER] == [[PNG]]
    router.route.assert_not_awaited()


async def test_new_image_turn_keeps_earlier_image_as_thumbnail():
    provider = FakeProvider([ModelResponse(content="看到两张图了。")])
    conversation = Conversation()
    conversation.add_user("旧图", images=[PNG])
    agent = ZhaoxiAgent(provider=provider, registry=ToolRegistry(),
                        context_builder=ContextBuilder("朝汐"), conversation=conversation)
    await agent.run("比较这两张图", images=[PNG], no_tools=True)
    pictured = [message for message in provider.calls[0] if message.role is Role.USER]
    assert pictured[0].images[0].startswith("data:image/jpeg;base64,")
    assert pictured[1].images == [PNG]


@pytest.mark.parametrize("question", ["现在能看到前面那个如龙里的人物吗", "他的眼镜什么颜色？"])
async def test_historical_images_survive_tool_finalization_without_image_keywords(tmp_path, question):
    from zhaoxi.cognitive_stream import ExperienceStream, AttentionRetriever
    from zhaoxi.cognitive_stream.ingress import CognitiveIngress
    from zhaoxi.cognitive_stream.turn import CognitiveTurnContext, set_current_turn, reset_current_turn
    from zhaoxi.tools.builtin import create_builtin_tools

    stream = ExperienceStream(tmp_path / "experience.db")
    ingress = CognitiveIngress(stream)
    conversation = Conversation()
    old = conversation.add_user("这张图呢？", images=[PNG, PNG])
    ingress.desktop(old.content, message_id=old.message_id, images=old.images, channel="web")
    conversation.add_assistant("之前的回复误称只能看到文字。")
    trigger = ingress.desktop(question, channel="web")
    builder = ContextBuilder("朝汐")
    builder.attention_retriever = AttentionRetriever(stream)
    registry = ToolRegistry()
    for tool in create_builtin_tools():
        registry.register(tool)
    provider = FakeProvider([
        ModelResponse(tool_calls=[ToolCall(id="time-1", name="current_time", arguments={})]),
        ModelResponse(content="现在仍能看到历史图片。"),
    ])
    agent = ZhaoxiAgent(provider=provider, registry=registry, context_builder=builder,
                        conversation=conversation, tool_router_mode="all")
    token = set_current_turn(CognitiveTurnContext(trigger_event=trigger, output_channel="web"))
    try:
        await agent.run_direct(question)
    finally:
        reset_current_turn(token)
    assert len(provider.calls) == 2
    assert provider.tool_schemas[1]
    initial = [image for message in provider.calls[0] for image in message.images]
    final = [image for message in provider.calls[1] for image in message.images]
    assert len(initial) == 2
    assert all(image.startswith("data:image/jpeg;base64,") for image in initial)
    assert final == initial
    assert stream.get(trigger.event_id).content == question
    assert old.images == [PNG, PNG]
