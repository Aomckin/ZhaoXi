import httpx
import pytest

from zhaoxi.core.message import Message, Role
from zhaoxi.errors import ProviderError
from zhaoxi.models.openai_compatible import OpenAICompatibleProvider


@pytest.mark.asyncio
async def test_provider_normalizes_tool_calls():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret"
        return httpx.Response(200, json={
            "id": "response-1",
            "model": "test-model",
            "choices": [{
                "finish_reason": "tool_calls",
                "message": {"content": None, "tool_calls": [{
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "calculator", "arguments": '{"expression":"2+2"}'},
                }]},
            }],
            "usage": {"total_tokens": 10},
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test/v1", api_key="secret", model="test-model", client=client
        )
        response = await provider.generate([Message(role=Role.USER, content="2+2")], [])
    assert response.tool_calls[0].arguments == {"expression": "2+2"}
    assert response.usage["total_tokens"] == 10


@pytest.mark.asyncio
async def test_provider_wraps_http_errors():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="failed")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test/v1", api_key="secret", model="test-model", client=client
        )
        with pytest.raises(ProviderError, match="模型请求失败"):
            await provider.generate([Message(role=Role.USER, content="hello")])

