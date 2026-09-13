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


async def test_natural_memory_create_and_update_need_no_write_confirmation(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    provider = FakeProvider([
        ModelResponse(tool_calls=[ToolCall(id="remember", name="remember_memory", arguments={"content": "楼下可乐现在四元"})]),
        ModelResponse(content="嗯，涨价了呀。"),
    ])
    agent = make_memory_agent(provider, service)
    response = await agent.run("今天楼下可乐涨价到四元了")
    assert response.permission_confirmation is None
    result = json.loads(provider.calls[1][-1].content)
    assert result["success"] and result["data"]["created"]
    memory_id = result["data"]["memory"]["id"]
    provider.responses.clear()
    provider.responses.extend([
        ModelResponse(tool_calls=[ToolCall(id="update", name="update_memory", arguments={"memory_id": memory_id, "content": "楼下可乐现在五元"})]),
        ModelResponse(content="原来是五元。"),
    ])
    response = await agent.run("其实刚才看错了，是五元")
    assert response.permission_confirmation is None
    result = json.loads(provider.calls[-1][-1].content)
    assert result["success"] and result["data"]["content"] == "楼下可乐现在五元"


@pytest.mark.parametrize("name", ["remember_memory", "update_memory"])
@pytest.mark.parametrize("intent", ["不要记住这件事", "别保存", "不要更新记忆", "只读，不要修改"])
async def test_user_can_forbid_automatic_memory_writes(tmp_path, name, intent):
    from zhaoxi.permission.models import InvocationOrigin
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    agent = make_memory_agent(FakeProvider([]), service)
    arguments = {"content": "不应保存的测试内容"}
    if name == "update_memory":
        arguments["memory_id"] = "not-executed"
    result = await agent.tool_executor.execute(name, arguments, request_id="deny", origin=InvocationOrigin.AGENT, user_intent=intent)
    assert not result.waiting_for_permission
    assert not result.result.success
    assert result.result.error in {"memory_forbidden_intent", "read_only_intent"}


def test_explicit_write_deny_still_blocks_memory():
    from zhaoxi.permission.models import PermissionLevel, PermissionStatus, PermissionRequest, InvocationOrigin
    from zhaoxi.permission.policy import DefaultPermissionPolicy
    policy = DefaultPermissionPolicy({PermissionLevel.WRITE: PermissionStatus.DENY})
    request = PermissionRequest(request_id="deny", tool_name="remember_memory", permission=PermissionLevel.WRITE,
                                arguments={}, arguments_digest="test", resource_scope="memory", action_summary="记录", origin=InvocationOrigin.AGENT)
    assert policy.evaluate(request).status == PermissionStatus.DENY
