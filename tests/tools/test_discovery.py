import json

import pytest

from conftest import FakeProvider
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.errors import AgentLoopError
from zhaoxi.models.types import ModelResponse, ToolCall
from zhaoxi.tools.discovery import RequestToolGroupTool, ToolDiscoveryState
from zhaoxi.tools.router import resolve_tool_context
from test_tool_router import make_registry


def state(registry, message="闲聊"):
    return ToolDiscoveryState(resolve_tool_context(message, [], registry))


def call(name, **arguments):
    return ModelResponse(tool_calls=[ToolCall(id=name, name=name, arguments=arguments)])


def names(schemas):
    return {schema["function"]["name"] for schema in schemas}


def test_expansion_validation_deduplication_and_limit():
    registry = make_registry()
    current = state(registry)
    for arguments in ({"group": "all"}, {}, {"group": []}, {"group": "web", "extra": True}):
        assert current.request(arguments, registry).error == "invalid_group"
    assert current.request({"group": "archive"}, registry).success
    assert current.request({"group": "archive"}, registry).success
    assert current.expansion_count == 1
    assert current.request({"group": "time"}, registry).success
    assert current.request({"group": "web"}, registry).error == "expansion_limit"
    assert len(current.expanded) == len(set(current.expanded))
    assert current.diagnostics(registry)["capability_expansion_count"] == 2
    assert "archive_search" in names(current.schemas(registry))
    assert "archive_search" not in names(state(registry).schemas(registry))


def test_preloaded_group_and_missing_provider():
    registry = make_registry()
    current = state(registry, "去潮庭查一下档案")
    assert current.request({"group": "archive"}, registry).success
    assert current.expansion_count == 0
    registry.unregister("mcp_fetch_fetch")
    assert "web" not in current.known(registry)
    assert current.request({"group": "web"}, registry).error == "unavailable_group"


async def test_discovery_continues_business_call_retains_schema_and_resets_next_turn():
    registry = make_registry()
    provider = FakeProvider([
        call("request_tool_group", group="archive"),
        call("archive_search"),
        ModelResponse(content="完成"),
        ModelResponse(content="你好"),
    ])
    agent = ZhaoxiAgent(provider=provider, registry=registry, context_builder=ContextBuilder("朝汐"))
    result = await agent.run("找下那把钥匙", require_tool_call=True)
    assert result.used_tool_path
    assert names(provider.tool_schemas[0]) == {"remember_memory", "update_memory", "search_memories", "request_tool_group", "inspect_tool_catalog"}
    assert "archive_search" in names(provider.tool_schemas[1])
    assert "archive_search" in names(provider.tool_schemas[2])
    tool_results = [json.loads(m.content) for m in provider.calls[2] if m.role.value == "tool"]
    assert len(tool_results) == 2 and all(item["success"] for item in tool_results)
    await agent.run("你好")
    assert "archive_search" not in names(provider.tool_schemas[3])
    catalog = provider.calls[0][0].content
    assert "钥匙柜" in catalog and "archive: 潮庭档案" in catalog
    assert f"registered_tools={len(registry.list())}" in catalog


async def test_discovery_alone_does_not_count_as_business_lookup():
    provider = FakeProvider([call("request_tool_group", group="archive"), ModelResponse(content="好了")])
    agent = ZhaoxiAgent(provider=provider, registry=make_registry(), context_builder=ContextBuilder("朝汐"))
    result = await agent.run("找那把钥匙", require_tool_call=True)
    assert result.content == "好了\n\n（提醒：这次没有实际调用工具，回复未经工具核验。）"
    assert result.used_tool_path is False


def test_discovery_schema_is_small_and_excludes_all():
    schema = RequestToolGroupTool().schema()
    assert schema["function"]["parameters"]["properties"]["group"]["not"] == {"const": "all"}
    assert len(json.dumps(schema, ensure_ascii=False)) < 1000


def test_memory_semantics_and_confirmation():
    from zhaoxi.tools.builtin.memory_tools import RememberMemoryTool, UpdateMemoryTool
    assert "无需等待" in RememberMemoryTool.description
    assert "无需明确" in UpdateMemoryTool.description
    assert "用户明确要求记住时调用" not in ContextBuilder.RUNTIME_RULES
    assert RememberMemoryTool(None).confirmation_description({}) == "朝汐想记录一条长期记忆"
    assert UpdateMemoryTool(None).confirmation_description({}) == "朝汐想更新一条已有记忆"


async def test_expansion_survives_permission_and_remaining_discovery_calls():
    from zhaoxi.permission.models import PermissionLevel, SideEffect
    registry = make_registry()
    write = registry.get("mcp_filesystem_write_file")
    write.permission = PermissionLevel.WRITE
    write.side_effects = frozenset({SideEffect.LOCAL_STATE})
    provider = FakeProvider([
        call("request_tool_group", group="archive"),
        ModelResponse(tool_calls=[
            ToolCall(id="write", name="mcp_filesystem_write_file"),
            ToolCall(id="time", name="request_tool_group", arguments={"group": "time"}),
        ]),
        call("request_tool_group", group="web"),
        call("archive_search"),
        ModelResponse(content="完成"),
    ])
    agent = ZhaoxiAgent(provider=provider, registry=registry, context_builder=ContextBuilder("朝汐"))
    pending = await agent.run("今天有点变化")
    assert pending.permission_confirmation
    result = await agent.approve_permission(pending.permission_confirmation.confirmation_id)
    assert result.content == "完成"
    for schemas in provider.tool_schemas[2:]:
        assert {"archive_search", "current_time"} <= names(schemas)
        assert "mcp_fetch_fetch" not in names(schemas)
    results = [json.loads(m.content) for m in provider.calls[-1] if m.role.value == "tool"]
    assert any(item["error"] == "expansion_limit" for item in results)


def test_all_mode_requests_do_not_expand_and_diagnostics_are_metadata_only():
    registry = make_registry()
    current = ToolDiscoveryState(resolve_tool_context("私密原文", [], registry, mode="all"))
    assert current.request({"group": "web"}, registry).success
    assert current.expansion_count == 0
    report = current.diagnostics(registry)
    assert set(report["final_exposed_tools"]) == {tool.name for tool in registry.list()}
    assert "私密原文" not in json.dumps(report, ensure_ascii=False)
    assert "parameters" not in json.dumps(report)
