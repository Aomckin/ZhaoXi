import json

import httpx
import pytest

from conftest import FakeProvider
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.errors import AgentLoopError, ProviderError
from zhaoxi.models.openai_compatible import OpenAICompatibleProvider
from zhaoxi.models.types import ModelResponse, ToolCall
from zhaoxi.memory.service import MemoryService
from zhaoxi.memory.sqlite import SQLiteMemoryRepository
from zhaoxi.tools.builtin import create_memory_tools


def make_agent(provider, registry, context_builder, conversation, max_steps=8):
    return ZhaoxiAgent(
        provider=provider,
        registry=registry,
        context_builder=context_builder,
        conversation=conversation,
        max_steps=max_steps,
    )


@pytest.mark.asyncio
async def test_direct_answer(registry, context_builder, conversation):
    provider = FakeProvider([ModelResponse(content="先休息一下吧。")])
    response = await make_agent(provider, registry, context_builder, conversation).run("今天有点累")
    assert response.content == "先休息一下吧。"
    assert response.steps == 1


@pytest.mark.asyncio
async def test_ordinary_agent_turn_exposes_persistent_memory_tools(
    context_builder, conversation, tmp_path
):
    from zhaoxi.tools.registry import ToolRegistry

    registry = ToolRegistry()
    for tool in create_memory_tools(MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))):
        registry.register(tool)
    provider = FakeProvider([ModelResponse(content="早呀。")])

    await make_agent(provider, registry, context_builder, conversation).run_direct("周六早上了呀")

    names = {item["function"]["name"] for item in provider.tool_schemas[0]}
    assert names == {"remember_memory", "update_memory", "search_memories", "request_tool_group", "inspect_tool_catalog"}


@pytest.mark.asyncio
async def test_tool_call_result_is_returned_to_model(registry, context_builder, conversation):
    provider = FakeProvider([
        ModelResponse(tool_calls=[ToolCall(id="c1", name="calculator", arguments={"expression": "17*23"})]),
        ModelResponse(content="17 × 23 等于 391。"),
    ])
    response = await make_agent(provider, registry, context_builder, conversation).run("算 17*23")
    assert response.content.endswith("391。")
    tool_message = provider.calls[1][-1]
    assert tool_message.name == "calculator"
    assert json.loads(tool_message.content)["data"]["result"] == 391


@pytest.mark.asyncio
async def test_dsml_tool_call_enters_the_same_agent_runtime(
    registry, context_builder, conversation
):
    responses = iter([
        {
            "id": "dsml-call",
            "choices": [{"message": {"content": (
                '<|DSML|tool_calls><|DSML|invoke name="echo">'
                '<|DSML|parameter name="message" string="true">hi</|DSML|parameter>'
                '</|DSML|invoke></|DSML|tool_calls>'
            )}}],
        },
        {
            "id": "final-answer",
            "choices": [{"message": {"content": "工具已正常执行。"}}],
        },
    ])

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(responses))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test/v1", api_key="secret", model="test-model", client=client
        )
        response = await make_agent(
            provider, registry, context_builder, conversation
        ).run("回显 hi")

    assert response.content == "工具已正常执行。"
    assert "DSML" not in response.content
    tool_messages = [message for message in conversation.messages if message.name == "echo"]
    assert json.loads(tool_messages[0].content)["data"]["message"] == "hi"


@pytest.mark.asyncio
async def test_qwen_text_call_uses_normal_tool_loop_with_native_schemas(
    registry, context_builder, conversation
):
    requests = []
    responses = iter([
        {
            "id": "qwen-text-call",
            "choices": [{"message": {"content": (
                "<tool_call><function=echo>"
                "<parameter=message>hi</parameter>"
                "</function></tool_call>"
            )}}],
        },
        {
            "id": "qwen-final-answer",
            "choices": [{"message": {"content": "工具已正常执行。"}}],
        },
    ])

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=next(responses))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test/v1", api_key="secret", model="qwen3.8-flash", client=client
        )
        response = await make_agent(
            provider, registry, context_builder, conversation
        ).run("回显 hi")

    assert response.content == "工具已正常执行。"
    assert requests[0]["tools"]
    assert [message["role"] for message in requests[1]["messages"][-3:]] == [
        "user", "assistant", "user",
    ]
    assert "tool_calls" not in requests[1]["messages"][-2]
    assert "Internal tool calls requested: echo" in requests[1]["messages"][-2]["content"]
    assert "Internal tool result for echo" in requests[1]["messages"][-1]["content"]
    assert "tool_call" not in response.content


@pytest.mark.asyncio
async def test_multiple_tools_in_one_step(registry, context_builder, conversation):
    provider = FakeProvider([
        ModelResponse(tool_calls=[
            ToolCall(id="c1", name="echo", arguments={"message": "hi"}),
            ToolCall(id="c2", name="calculator", arguments={"expression": "12*17"}),
        ]),
        ModelResponse(content="hi，结果是 204。"),
    ])
    response = await make_agent(provider, registry, context_builder, conversation).run("测试")
    assert response.steps == 2
    assert [message.name for message in provider.calls[1][-2:]] == ["echo", "calculator"]


@pytest.mark.asyncio
async def test_missing_tool_becomes_observation(registry, context_builder, conversation):
    provider = FakeProvider([
        ModelResponse(tool_calls=[ToolCall(id="bad", name="missing", arguments={})]),
        ModelResponse(content="这个工具目前不可用。"),
    ])
    response = await make_agent(provider, registry, context_builder, conversation).run("调用不存在的工具")
    observation = json.loads(provider.calls[1][-1].content)
    assert observation["success"] is False
    assert response.content == "这个工具目前不可用。"


@pytest.mark.asyncio
async def test_invalid_arguments_become_observation(registry, context_builder, conversation):
    provider = FakeProvider([
        ModelResponse(tool_calls=[ToolCall(id="bad", name="calculator", arguments={})]),
        ModelResponse(content="缺少表达式，无法计算。"),
    ])
    await make_agent(provider, registry, context_builder, conversation).run("计算")
    assert json.loads(provider.calls[1][-1].content)["success"] is False


@pytest.mark.asyncio
async def test_loop_guard(registry, context_builder, conversation):
    repeating = ModelResponse(tool_calls=[ToolCall(id="again", name="echo", arguments={"message": "x"})])
    provider = FakeProvider([repeating])
    response = await make_agent(provider, registry, context_builder, conversation, max_steps=2).run("循环")
    assert response.used_tool_path
    assert response.content == (
        "工具操作已经完成，但模型没能整理成自然语言回复。\n\n"
        "（提醒：工具步骤已达到本轮上限，回复可能不完整；已完成的操作已保留。）"
    )
    assert "x" not in response.content


@pytest.mark.asyncio
async def test_retryable_provider_failure_after_tool_returns_partial_result(
    registry, context_builder, conversation
):
    provider = FakeProvider([ModelResponse(tool_calls=[
        ToolCall(id="calc", name="calculator", arguments={"expression": "12*17"})
    ])])
    original_generate = provider.generate
    calls = 0

    async def generate(messages, tools=None, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ProviderError("temporary", retryable=True)
        return await original_generate(messages, tools, **kwargs)

    provider.generate = generate
    response = await make_agent(provider, registry, context_builder, conversation).run("计算 12*17")
    assert response.used_tool_path
    assert response.content == (
        "工具操作已经完成，但模型没能整理成自然语言回复。\n\n"
        "（提醒：模型服务暂时不可用，这段回复可能不完整；已完成的工具操作已保留。）"
    )


@pytest.mark.asyncio
async def test_nonretryable_provider_failure_after_tool_returns_tool_result(
    registry, context_builder, conversation
):
    provider = FakeProvider([ModelResponse(tool_calls=[
        ToolCall(id="calc", name="calculator", arguments={"expression": "12*17"})
    ])])
    original_generate = provider.generate
    calls = 0

    async def generate(messages, tools=None, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ProviderError("bad auth", code="provider_http_401", retryable=False)
        return await original_generate(messages, tools, **kwargs)

    provider.generate = generate
    response = await make_agent(provider, registry, context_builder, conversation).run("计算 12*17")
    assert response.content == (
        "工具操作已经完成，但模型没能整理成自然语言回复。\n\n"
        "（提醒：模型服务暂时不可用，这段回复可能不完整；已完成的工具操作已保留。）"
    )


@pytest.mark.asyncio
async def test_invalid_tool_json_after_failed_tool_returns_failure_summary(
    registry, context_builder, conversation
):
    provider = FakeProvider([ModelResponse(tool_calls=[
        ToolCall(id="bad", name="calculator", arguments={"expression": ""})
    ])])
    original_generate = provider.generate
    calls = 0

    async def generate(messages, tools=None, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ProviderError(
                "invalid tool JSON",
                code="provider_tool_arguments_invalid",
                retryable=False,
            )
        return await original_generate(messages, tools, **kwargs)

    provider.generate = generate
    response = await make_agent(provider, registry, context_builder, conversation).run("计算")
    assert "工具操作未能完成" in response.content
    assert "后续工具参数格式有误" in response.content
