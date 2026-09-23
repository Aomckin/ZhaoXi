import json

import pytest

from conftest import FakeProvider
from test_tool_router import NamedTool, make_registry
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.models.types import ModelResponse, ToolCall
from zhaoxi.permission.executor import ToolExecutor
from zhaoxi.permission.models import InvocationOrigin, PermissionLevel, SideEffect
from zhaoxi.tools.discovery import ToolDiscoveryState
from zhaoxi.tools.manifest import resolve_capability
from zhaoxi.tools.registry import ToolRegistry
from zhaoxi.tools.router import resolve_tool_context


def state(registry, message="今天太阳有点像夏天"):
    return ToolDiscoveryState(resolve_tool_context(message, [], registry))


def names(current, registry):
    return {s["function"]["name"] for s in current.schemas(registry)}


def test_memory_core_inventory_and_dynamic_registration():
    registry = make_registry()
    current = state(registry)
    assert {"remember_memory", "update_memory", "search_memories"} <= names(current, registry)
    summary = current.inspect({"action": "summary"}, registry).data
    assert summary["registered_tools"] == len(registry.list()) > summary["currently_exposed"] == 5
    assert len(current.inspect({"action": "inspect_group", "group": "memory_core"}, registry).data) == 3
    tool = NamedTool("future_tool")
    tool.group = "future"
    tool.source = "new-package"
    tool.aliases = ["明日安排"]
    registry.register(tool)
    assert "future" in current.known(registry)
    assert resolve_capability("请查明日安排", registry.manifest())["groups"] == ["future"]
    assert current.request({"group": "future"}, registry).success
    assert "future_tool" in names(current, registry)
    record = current.inspect({"action": "inspect_tool", "name": "future_tool"}, registry).data
    assert record["source"] == "new-package" and record["exposed"]
    registry.unregister("future_tool")
    assert "future" not in current.known(registry)
    assert "future_tool" not in names(current, registry)


def test_known_tools_expose_short_chinese_labels_and_usage():
    registry = make_registry()
    record = next(
        item for item in registry.manifest()
        if item["name"] == "mcp_filesystem_write_file"
    )
    assert record["display_name"] == "新建或覆盖文件"
    assert record["usage"] == "新建文件或完整覆盖已有文件。"


async def test_disabled_state_propagates_to_every_layer_and_executor():
    registry = make_registry()
    current = state(registry)
    current.request({"group": "web"}, registry)
    registry.update_tools(group="web", enabled=False, force_expose=True)
    record = next(t for t in registry.manifest() if t["group"] == "web")
    assert record["registered"] and record["available"] and not record["enabled"]
    assert "mcp_fetch_fetch" not in names(current, registry)
    assert "mcp_fetch_fetch" not in resolve_tool_context("请读网页", [], registry, mode="all").exposed_tools
    assert resolve_capability("请读网页", registry.manifest())["groups"] == []
    assert "web" in resolve_capability("请读网页", registry.manifest())["unavailable_groups"]
    assert "已停用" in current.catalog(registry)
    assert not current.request({"group": "web"}, registry).success
    result = await ToolExecutor(registry).execute("mcp_fetch_fetch", {}, request_id="test", origin=InvocationOrigin.AGENT)
    assert result.result.error == "tool_unavailable"


def test_force_expose_removal_is_immediate_and_respects_availability():
    registry = make_registry()
    registry.update_tools(name="mcp_fetch_fetch", force_expose=True)
    current = state(registry)
    assert "mcp_fetch_fetch" in names(current, registry)
    registry.update_tools(name="mcp_fetch_fetch", force_expose=False)
    assert "mcp_fetch_fetch" not in names(current, registry)
    registry.update_tools(name="mcp_fetch_fetch", force_expose=True)
    registry.get("mcp_fetch_fetch").available = False
    assert "mcp_fetch_fetch" not in names(current, registry)
    record = next(t for t in registry.manifest() if t["name"] == "mcp_fetch_fetch")
    assert record["enabled"] and not record["available"]
    assert "依赖不可用" in current.catalog(registry)


def test_overrides_survive_restart_and_all_reset_scopes(tmp_path):
    path = tmp_path / "overrides.json"
    def build():
        registry = ToolRegistry(path)
        tool = NamedTool("new_tool")
        tool.default_enabled = False
        tool.group = "new"
        registry.register(tool)
        return registry
    registry = build()
    registry.update_tools(
        name="new_tool", enabled=True, force_expose=True, confirm_write=False
    )
    restarted = build()
    assert restarted.manifest()[0]["enabled"] and restarted.manifest()[0]["force_expose"]
    assert restarted.manifest()[0]["confirm_write"] is False
    for kwargs in ({"name": "new_tool"}, {"group": "new"}, {}):
        registry.update_tools(name="new_tool", enabled=True)
        registry.update_tools(**kwargs, reset=True)
        assert not registry.manifest()[0]["enabled"]
        assert json.loads(path.read_text()) == {}


def test_failed_persistence_does_not_apply_runtime_change(tmp_path, monkeypatch):
    from pathlib import Path
    registry = ToolRegistry(tmp_path / "overrides.json")
    registry.register(NamedTool("test"))
    def fail(*args):
        raise OSError("cannot persist")
    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError):
        registry.update_tools(name="test", enabled=False)
    assert registry.usable("test")


async def test_resolve_load_execute_when_router_misses(monkeypatch):
    import zhaoxi.tools.router as router
    monkeypatch.setattr(router, "_dynamic_groups", lambda *args: ((), ()))
    monkeypatch.setattr(router, "is_action_request", lambda *args: False)
    registry = make_registry()
    provider = FakeProvider([
        ModelResponse(tool_calls=[ToolCall(id="1", name="inspect_tool_catalog", arguments={"action": "resolve", "need": "搜索本地电脑里的文件"})]),
        ModelResponse(tool_calls=[ToolCall(id="2", name="request_tool_group", arguments={"group": "local_search"})]),
        ModelResponse(tool_calls=[ToolCall(id="3", name="mcp_everything-search_search")]),
        ModelResponse(content="找到了"),
    ])
    agent = ZhaoxiAgent(provider=provider, registry=registry, context_builder=ContextBuilder("朝汐"))
    result = await agent.run("帮我找桌面上的面试复盘", require_tool_call=True)
    assert result.content == "找到了"
    assert not any(m.role.value == "tool" for m in provider.calls[1])
    assert not any(m.role.value == "tool" for m in provider.calls[2])
    assert "inspect_tool_catalog:" in provider.calls[1][0].content
    assert "request_tool_group" in provider.calls[2][0].content
    assert "mcp_everything-search_search" not in {s["function"]["name"] for s in provider.tool_schemas[0]}
    assert "mcp_everything-search_search" in {s["function"]["name"] for s in provider.tool_schemas[2]}


async def test_unfounded_refusal_checks_and_loads_catalog(monkeypatch):
    import zhaoxi.tools.router as router
    monkeypatch.setattr(router, "_dynamic_groups", lambda *args: ((), ()))
    monkeypatch.setattr(router, "is_action_request", lambda *args: False)
    provider = FakeProvider([
        ModelResponse(content="我没有搜索工具"),
        ModelResponse(tool_calls=[ToolCall(id="real", name="mcp_everything-search_search")]),
        ModelResponse(content="完成"),
    ])
    agent = ZhaoxiAgent(provider=provider, registry=make_registry(), context_builder=ContextBuilder("朝汐"))
    assert (await agent.run("帮我找桌面文件")).content == "完成"
    assert "Core 已检查实时钥匙柜" in provider.calls[1][0].content


async def test_disabled_after_permission_pause_cannot_execute():
    registry = make_registry()
    tool = registry.get("mcp_filesystem_write_file")
    tool.permission = PermissionLevel.WRITE
    tool.side_effects = frozenset({SideEffect.LOCAL_STATE})
    provider = FakeProvider([ModelResponse(tool_calls=[ToolCall(id="write", name="mcp_filesystem_write_file")]), ModelResponse(content="已停用")])
    agent = ZhaoxiAgent(provider=provider, registry=registry, context_builder=ContextBuilder("朝汐"))
    pending = await agent.run("今天有变化")
    registry.update_tools(name="mcp_filesystem_write_file", enabled=False)
    await agent.approve_permission(pending.permission_confirmation.confirmation_id)
    result = next(m for m in provider.calls[-1] if m.role.value == "tool")
    assert json.loads(result.content)["error"] == "tool_unavailable"


async def test_inventory_question_is_satisfied_by_actual_inventory_query():
    provider = FakeProvider([
        ModelResponse(tool_calls=[ToolCall(id="inventory", name="inspect_tool_catalog", arguments={"action": "summary"})]),
        ModelResponse(content="完整清单已查过"),
    ])
    agent = ZhaoxiAgent(provider=provider, registry=make_registry(), context_builder=ContextBuilder("朝汐"))
    assert (await agent.run("你一共有多少把钥匙？", require_tool_call=True)).content == "完整清单已查过"


def test_mcp_dependency_health_is_live_without_network():
    from types import SimpleNamespace
    from tools.mcp.adapter import MCPTool
    client = SimpleNamespace(running=True)
    tool = MCPTool(client, "fetch", {"name": "fetch", "annotations": {"readOnlyHint": True}})
    registry = ToolRegistry()
    registry.register(tool)
    assert registry.usable(tool.name)
    client.running = False
    assert registry.manifest()[0]["enabled"] and not registry.manifest()[0]["available"]
    assert not registry.usable(tool.name)
    client.running = True
    assert registry.usable(tool.name)
