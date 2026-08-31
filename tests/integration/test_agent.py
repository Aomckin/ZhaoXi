import json

import httpx
import pytest

from conftest import FakeProvider
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.errors import AgentLoopError
from zhaoxi.models.openai_compatible import OpenAICompatibleProvider
from zhaoxi.models.types import ModelResponse, ToolCall


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
    with pytest.raises(AgentLoopError, match="最大执行步数"):
        await make_agent(provider, registry, context_builder, conversation, max_steps=2).run("循环")
