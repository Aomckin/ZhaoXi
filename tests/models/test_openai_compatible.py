import httpx
import logging
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
async def test_provider_classifies_malformed_native_tool_arguments():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": None, "tool_calls": [{
                "id": "bad-call",
                "function": {"name": "add_job", "arguments": '{"company":'},
            }]}}],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test/v1", api_key="secret", model="test-model", client=client
        )
        with pytest.raises(ProviderError) as caught:
            await provider.generate([Message(role=Role.USER, content="记录岗位")], [])

    assert caught.value.code == "provider_tool_arguments_invalid"
    assert not caught.value.retryable


@pytest.mark.asyncio
async def test_provider_normalizes_dsml_text_tool_calls_and_hides_protocol():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "id": "response-dsml",
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": """好的，我来结束专注。
<|DSML|tool_calls>
<|DSML|invoke name=\"lifehud_focus_stop\">
<|DSML|parameter name=\"focusId\" string=\"true\">focus-123</|DSML|parameter>
<|DSML|parameter name=\"note\" string=\"true\">用户结束测试</|DSML|parameter>
</|DSML|invoke>
</|DSML|tool_calls>"""},
            }],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test/v1", api_key="secret", model="test-model", client=client
        )
        response = await provider.generate([Message(role=Role.USER, content="结束专注")])

    assert response.content == "好的，我来结束专注。"
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "lifehud_focus_stop"
    assert response.tool_calls[0].arguments == {
        "focusId": "focus-123",
        "note": "用户结束测试",
    }
    assert "DSML" not in (response.content or "")


@pytest.mark.asyncio
async def test_provider_normalizes_empty_argument_dsml_call():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": (
                '<|DSML|tool_calls><|DSML|invoke name="lifehud_focus_current">'
                '</|DSML|invoke></|DSML|tool_calls>'
            )}}],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test/v1", api_key="secret", model="test-model", client=client
        )
        response = await provider.generate([Message(role=Role.USER, content="当前专注")])

    assert response.content is None
    assert response.tool_calls[0].name == "lifehud_focus_current"
    assert response.tool_calls[0].arguments == {}


@pytest.mark.asyncio
async def test_provider_accepts_spaced_double_pipe_dsml_variant_from_deepseek():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": """
<| | DSML | | tool_calls>
<| | DSML | | invoke name=“forget_memory”>
<| | DSML | | parameter name=“memory_id” string=“true”>944d2cf1</| | DSML | | parameter>
</| | DSML | | invoke>
</| | DSML | | tool_calls>
"""}}],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test/v1", api_key="secret", model="test-model", client=client
        )
        response = await provider.generate([Message(role=Role.USER, content="忘掉它")])

    assert response.content is None
    assert response.tool_calls[0].name == "forget_memory"
    assert response.tool_calls[0].arguments == {"memory_id": "944d2cf1"}


@pytest.mark.asyncio
async def test_structured_calls_win_without_leaking_duplicate_dsml():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {
                "content": (
                    '<|DSML|tool_calls><|DSML|invoke name="duplicate">'
                    '</|DSML|invoke></|DSML|tool_calls>'
                ),
                "tool_calls": [{
                    "id": "structured-1",
                    "function": {"name": "preferred", "arguments": "{}"},
                }],
            }}],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test/v1", api_key="secret", model="test-model", client=client
        )
        response = await provider.generate([Message(role=Role.USER, content="run")])

    assert response.content is None
    assert [call.name for call in response.tool_calls] == ["preferred"]


@pytest.mark.asyncio
async def test_provider_normalizes_qwen_text_tool_call_and_hides_xml():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "id": "response-qwen-text",
            "choices": [{"message": {"content": """准备查询。
<tool_call>
<function=archive_search>
<parameter=query>
钥匙 潮庭 记忆门 数量
</parameter>
</function>
</tool_call>"""}}],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test/v1", api_key="secret", model="qwen3.8-flash", client=client
        )
        response = await provider.generate([Message(role=Role.USER, content="查询钥匙")])

    assert response.content == "准备查询。"
    assert response.tool_calls[0].name == "archive_search"
    assert response.tool_calls[0].arguments == {"query": "钥匙 潮庭 记忆门 数量"}
    assert "tool_call" not in (response.content or "")


@pytest.mark.asyncio
async def test_native_calls_win_without_leaking_duplicate_qwen_xml():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {
                "content": (
                    "<tool_call><function=duplicate>"
                    "</function></tool_call>"
                ),
                "tool_calls": [{
                    "id": "structured-qwen-1",
                    "function": {"name": "preferred", "arguments": "{}"},
                }],
            }}],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test/v1", api_key="secret", model="qwen3.8-flash", client=client
        )
        response = await provider.generate([Message(role=Role.USER, content="run")])

    assert response.content is None
    assert [call.name for call in response.tool_calls] == ["preferred"]


@pytest.mark.asyncio
async def test_malformed_qwen_xml_is_rejected_instead_of_exposed():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "<tool_call><function=archive_search>"}}],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test/v1", api_key="secret", model="qwen3.8-flash", client=client
        )
        with pytest.raises(ProviderError, match="文本工具调用协议") as caught:
            await provider.generate([Message(role=Role.USER, content="run")])
    assert caught.value.code == "provider_tool_arguments_invalid"


@pytest.mark.asyncio
async def test_malformed_dsml_is_rejected_instead_of_exposed():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '<|DSML|invoke name="secret">'}}],
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test/v1", api_key="secret", model="test-model", client=client
        )
        with pytest.raises(ProviderError, match="文本工具调用协议") as caught:
            await provider.generate([Message(role=Role.USER, content="run")])
    assert caught.value.code == "provider_tool_arguments_invalid"


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


@pytest.mark.asyncio
async def test_provider_logs_http_error_body_at_warning(caplog):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "invalid image_url", "code": "bad_request"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test/v1", api_key="secret", model="test-model", client=client
        )
        with caplog.at_level(logging.WARNING, logger="MODEL"):
            with pytest.raises(ProviderError) as caught:
                await provider.generate([Message(role=Role.USER, content="看图")])

    assert caught.value.code == "provider_http_400"
    assert not caught.value.retryable
    record = next(item for item in caplog.records if "provider http error" in item.message)
    output = record.getMessage()
    assert "status=400" in output
    assert "model=test-model" in output
    assert "retryable=False" in output
    assert "invalid image_url" in output


@pytest.mark.parametrize(
    ("status", "retryable"),
    [
        (400, False),
        (401, False),
        (403, False),
        (404, False),
        (422, False),
        (408, True),
        (429, True),
        (500, True),
        (502, True),
        (520, True),
    ],
)
@pytest.mark.asyncio
async def test_provider_classifies_http_status_retryability(status, retryable):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "upstream unavailable"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test/v1", api_key="secret", model="test-model", client=client
        )
        with pytest.raises(ProviderError) as caught:
            await provider.generate([Message(role=Role.USER, content="hello")])

    assert caught.value.code == f"provider_http_{status}"
    assert caught.value.retryable is retryable
