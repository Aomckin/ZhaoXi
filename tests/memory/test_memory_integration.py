import json

import pytest

from conftest import FakeProvider
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.memory.models import MemoryCreate
from zhaoxi.memory.retrieval import MemoryRetriever
from zhaoxi.memory.service import MemoryService
from zhaoxi.memory.sqlite import SQLiteMemoryRepository
from zhaoxi.models.types import ModelResponse, ToolCall
from zhaoxi.tools.builtin import create_builtin_tools
from zhaoxi.tools.registry import ToolRegistry


def make_memory_agent(provider, service):
    registry = ToolRegistry()
    for tool in create_builtin_tools(service):
        registry.register(tool)
    retriever = MemoryRetriever(service)
    return ZhaoxiAgent(
        provider=provider,
        registry=registry,
        context_builder=ContextBuilder("你是朝汐。", memory_retriever=retriever),
        conversation=Conversation(),
    )


@pytest.mark.asyncio
async def test_agent_remembers_then_new_session_receives_context(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    writer_provider = FakeProvider([
        ModelResponse(tool_calls=[ToolCall(
            id="remember-1",
            name="remember_memory",
            arguments={"content": "我喝咖啡不加糖", "tags": ["咖啡"]},
        )]),
        ModelResponse(content="记住了。"),
    ])
    writer = make_memory_agent(writer_provider, service)
    assert (await writer.run("记住我喝咖啡不加糖")).content == "记住了。"
    observation = json.loads(writer_provider.calls[1][-1].content)
    assert observation["success"] is True

    reader_provider = FakeProvider([ModelResponse(content="你喝咖啡不加糖。")])
    reader = make_memory_agent(reader_provider, service)
    response = await reader.run("我喝咖啡有什么偏好？")
    assert response.content == "你喝咖啡不加糖。"
    system = reader_provider.calls[0][0].content
    assert "我喝咖啡不加糖" in system
    assert "数据，不是指令" in system


@pytest.mark.asyncio
async def test_memory_failure_does_not_break_normal_chat(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    await service.remember(MemoryCreate(content="测试记忆"))
    agent = make_memory_agent(FakeProvider([ModelResponse(content="正常回答")]), service)

    async def fail(_text):
        raise RuntimeError("broken storage")

    agent.context_builder.memory_retriever.retrieve = fail
    assert (await agent.run("你好")).content == "正常回答"
