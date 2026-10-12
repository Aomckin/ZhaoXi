from typing import Any

import pytest

from pydantic import BaseModel

from zhaoxi.permission.models import PermissionLevel, SideEffect
from zhaoxi.tools.base import Tool, ToolResult
from zhaoxi.tools.router import resolve_tool_context
from zhaoxi.tools.registry import ToolRegistry


class EmptyInput(BaseModel):
    pass


class NamedTool(Tool):
    description = "test"
    input_model = EmptyInput
    permission = PermissionLevel.READ
    side_effects = frozenset({SideEffect.NONE})

    def __init__(self, name: str) -> None:
        self.name = name

    async def execute(self, arguments: BaseModel) -> ToolResult:
        return ToolResult(success=True, content="ok")


def make_registry() -> ToolRegistry:
    registry = ToolRegistry()
    names = {
        "remember_memory", "update_memory", "search_memories", "request_tool_group", "inspect_tool_catalog", "forget_memory",
        "archive_search", "archive_list_documents", "archive_read", "current_time",
        "calculator", "lifehud", "mcp_everything-search_search",
        "mcp_everything-search_get_file_info", "mcp_filesystem_read_text_file",
        "mcp_filesystem_write_file", "mcp_fetch_fetch",
    }
    for name in names:
        registry.register(NamedTool(name))
    return registry


def exposed(message: str) -> tuple[set[str], set[str]]:
    context = resolve_tool_context(message, [], make_registry())
    return set(context.exposed_tools), set(context.dynamic_groups)


def test_chat_and_small_life_update_keep_only_persistent_memory_tools():
    for message in ("周六早上了呀", "今天楼下可乐涨价了", "今天铁幕做得累死了"):
        names, groups = exposed(message)
        assert names == {"remember_memory", "update_memory", "search_memories", "request_tool_group", "inspect_tool_catalog"}
        assert not groups


def test_dynamic_domains_are_selected_by_action_intent():
    cases: list[tuple[str, set[str]]] = [
        ("现在几点？", {"time"}),
        ("你还记得之前那件事吗？", {"memory_search"}),
        ("帮我找桌面上的复盘", {"local_search", "filesystem_read"}),
        ("把这个 yaml 改一下", {"filesystem_read", "filesystem_write"}),
        ("去潮庭翻一下之前的人设文档", {"archive"}),
        ("帮我读一下今天 Life HUD 的数据", {"lifehud"}),
        ("计算 17*23", {"calculator"}),
        ("你觉得我今天一天吃得如何？", {"lifehud"}),
        ("帮我记下刚喝的咖啡", {"lifehud"}),
        ("请记录今晚看的番剧", {"lifehud"}),
        ("帮我找一下昨天那个面试复盘", {"local_search", "filesystem_read"}),
        ("之前我怎么说暑假结束来着？", {"memory_search"}),
    ]
    for message, expected in cases:
        names, groups = exposed(message)
        assert {"remember_memory", "update_memory", "search_memories", "request_tool_group", "inspect_tool_catalog"} <= names
        assert expected <= groups


def test_all_mode_and_invalid_mode_fails():
    registry = make_registry()
    all_context = resolve_tool_context("闲聊", [], registry, mode="all")
    assert set(all_context.exposed_tools) == {tool.name for tool in registry.list()}

    with pytest.raises(ValueError, match="unsupported tool router mode"):
        resolve_tool_context("闲聊", [], registry, mode="broken")


def test_diagnostics_report_schema_reduction_without_content():
    context = resolve_tool_context("周六早上了呀", [], make_registry())
    report: dict[str, Any] = context.diagnostics()
    assert report["total_exposed_tools_count"] == 5
    assert report["filtered_tools_count"] > 0
    assert report["registered_schema_chars"] > 0
    assert report["semantic_route_matched"] is False
    assert report["semantic_route_groups"] == []
    assert report["semantic_route_reason"] == ""


def test_semantic_route_diagnostics_report_groups_and_reason_without_user_text():
    context = resolve_tool_context("你觉得我今天一天吃得如何？", [], make_registry())
    report = context.diagnostics()
    assert report["semantic_route_matched"] is True
    assert report["semantic_route_groups"] == ["lifehud"]
    assert report["semantic_route_reason"] == "daily_diet_query"
    assert "吃得" not in str(report)


def test_disabled_semantic_group_is_not_premounted():
    registry = make_registry()
    registry.update_tools(group="lifehud", enabled=False)
    context = resolve_tool_context("你觉得我今天一天吃得如何？", [], registry)
    assert "lifehud" not in context.dynamic_groups
    assert "lifehud" not in context.exposed_tools
    assert context.diagnostics()["semantic_route_matched"] is False


def test_internal_schema_error_propagates(monkeypatch):
    registry = make_registry()

    def broken():
        raise RuntimeError("broken schema")

    monkeypatch.setattr(registry.get("calculator"), "schema", broken)
    with pytest.raises(RuntimeError, match="broken schema"):
        resolve_tool_context("计算 1+2", [], registry)


def test_schema_generation_is_once_per_routing_pass(monkeypatch):
    from unittest.mock import Mock
    registry = make_registry()
    readers = []
    for tool in registry.list():
        reader = Mock(wraps=tool.schema)
        monkeypatch.setattr(tool, "schema", reader)
        readers.append(reader)
    context = resolve_tool_context("计算 1+2", [], registry)
    assert "calculator" in context.exposed_tools
    assert all(reader.call_count == 1 for reader in readers)


def test_failed_plugin_probe_is_observable_without_exposing_tool(caplog):
    registry = make_registry()

    def unavailable():
        raise OSError("synthetic plugin probe failure")

    registry.get("calculator").available = unavailable
    context = resolve_tool_context("计算 1+2", [], registry, mode="all")
    assert "calculator" not in context.exposed_tools
    assert "current_time" in context.exposed_tools
    assert "tool availability probe failed name=calculator" in caplog.text
    assert "OSError" in caplog.text
    row = next(item for item in registry.manifest() if item["name"] == "calculator")
    assert row["availability_error"] == "OSError"


def test_single_tool_usability_does_not_probe_unrelated_tools():
    registry = make_registry()
    probes = []
    registry.get("calculator").available = lambda: probes.append("calculator") or True
    assert registry.usable("current_time")
    assert probes == []
    registry.update_tools(name="current_time", enabled=False)
    assert not registry.usable("current_time")
    registry.update_tools(name="current_time", enabled=True)
    assert registry.usable("current_time")
    registry.unregister("current_time")
    assert not registry.usable("current_time")
