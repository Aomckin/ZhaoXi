import json

import pytest

from conftest import FakeProvider
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.errors import AgentLoopError
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
