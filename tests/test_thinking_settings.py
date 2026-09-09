import json
import httpx
import pytest
from zhaoxi.models.openai_compatible import OpenAICompatibleProvider
from zhaoxi.core.message import Message, Role
from zhaoxi.models.types import ToolCall

async def test_thinking_switch_persists_and_replays_tool_reasoning(tmp_path):
    payloads=[]
    async def handle(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':'ok'},'finish_reason':'stop'}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        args=dict(base_url='https://api.deepseek.com',api_key='test',model='deepseek-chat',client=client,thinking_settings_path=str(tmp_path/'settings.json'))
        provider=OpenAICompatibleProvider(**args)
        assert provider.thinking_enabled is None
        provider.set_thinking(True)
        message=Message(role=Role.ASSISTANT,tool_calls=[ToolCall(id='t',name='tool')],metadata={'reasoning_content':'private reasoning'})
        await provider.generate([message])
        assert payloads[-1]['thinking']=={'type':'enabled'}
        assert payloads[-1]['messages'][0]['reasoning_content']=='private reasoning'
        provider=OpenAICompatibleProvider(**args)
        assert provider.thinking_enabled is True
        provider.set_thinking(False)
        await provider.generate([Message(role=Role.USER,content='hello')])
        assert payloads[-1]['thinking']=={'type':'disabled'}

def test_unsupported_provider_does_not_accept_thinking():
    provider=OpenAICompatibleProvider(base_url='https://example.com',api_key='test',model='test')
    assert not provider.supports_thinking
    with pytest.raises(ValueError):provider.set_thinking(True)
