"""Deterministic per-turn selection of tool schemas."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from zhaoxi.tools.registry import ToolRegistry


PERSISTENT_CORE = ("remember_memory", "update_memory")

TOOL_GROUPS: dict[str, tuple[str, ...]] = {
    "memory_search": ("search_memories",),
    "memory_admin": (
        "pin_memory", "forget_memory", "archive_memory",
        "reactivate_memory", "consolidate_memories",
    ),
    "archive": ("archive_search", "archive_list_documents", "archive_read"),
    "search": ("mcp_everything-search_search", "mcp_everything-search_get_file_info"),
    "filesystem_read": (
        "mcp_filesystem_read_text_file", "mcp_filesystem_read_file",
        "mcp_filesystem_read_multiple_files", "mcp_filesystem_read_media_file",
        "mcp_filesystem_get_file_info", "mcp_filesystem_list_directory",
        "mcp_filesystem_list_directory_with_sizes", "mcp_filesystem_directory_tree",
        "mcp_filesystem_search_files", "mcp_filesystem_list_allowed_directories",
    ),
    "filesystem_write": (
        "mcp_filesystem_write_file", "mcp_filesystem_edit_file",
        "mcp_filesystem_create_directory", "mcp_filesystem_move_file",
    ),
    "web": ("mcp_fetch_fetch",),
    "time": ("current_time", "mcp_time_get_current_time", "mcp_time_convert_time"),
    "calculator": ("calculator",),
    "lifehud": ("lifehud",),
    # Built-in developer utility. It is intentionally absent from normal turns.
    "echo": ("echo",),
}


@dataclass(frozen=True, slots=True)
class ToolContext:
    mode: str
    persistent_tools: tuple[str, ...]
    dynamic_groups: tuple[str, ...]
    exposed_tools: tuple[str, ...]
    reason_tags: tuple[str, ...]
    schemas: tuple[dict[str, Any], ...]
    registered_tools_count: int
    registered_schema_chars: int
    fallback: bool = False

    def diagnostics(self) -> dict[str, Any]:
        return {
            "router_mode": self.mode,
            "persistent_tools": list(self.persistent_tools),
            "persistent_tools_count": len(self.persistent_tools),
            "matched_dynamic_groups": list(self.dynamic_groups),
            "dynamic_tools_count": len(self.exposed_tools) - len(self.persistent_tools),
            "total_exposed_tools_count": len(self.exposed_tools),
            "total_registered_tools_count": self.registered_tools_count,
            "filtered_tools_count": self.registered_tools_count - len(self.exposed_tools),
            "registered_schema_chars": self.registered_schema_chars,
            "reason_tags": list(self.reason_tags),
            "fallback": self.fallback,
        }


def _schema_chars(schemas: Iterable[dict[str, Any]]) -> int:
    return len(json.dumps(list(schemas), ensure_ascii=False, separators=(",", ":"), default=str))


def _matches(pattern: str, text: str) -> bool:
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def _dynamic_groups(user_message: str, recent_context: Sequence[str] | str | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    current = user_message.strip()
    if isinstance(recent_context, str):
        recent = recent_context
    else:
        recent = "\n".join(str(item) for item in (recent_context or ()))
    contextual = f"{recent[-1600:]}\n{current}" if recent else current
    groups: list[str] = []
    reasons: list[str] = []

    def add(group: str, reason: str) -> None:
        if group not in groups:
            groups.append(group)
            reasons.append(reason)

    action = _matches(r"(?:帮我|请|能否|可以|麻烦|去|把|给我|替我|我要|我想).{0,10}(?:找|查|搜|看|翻|读|打开|列出|修改|改一下|编辑|写入|新建|移动|计算|算一下|获取)|(?:找|查|搜|翻|读取|打开|修改|改一下|编辑|写入|新建|移动|计算|几点|什么时间|几号)", current)
    if _matches(r"(?:还记得|记不记得|之前聊过|上次那|以前记过|回忆一下|查.*记忆)", current):
        add("memory_search", "memory_recall_request")
    if _matches(r"(?:置顶|固定|忘掉|忘记这|删除.*记忆|归档.*记忆|恢复.*记忆|重新激活.*记忆|整理.*记忆|合并.*记忆)", current):
        add("memory_admin", "memory_management_request")
    if _matches(r"(?:潮庭|archive|档案库)", current) and action:
        add("archive", "archive_access_request")
    if _matches(r"(?:文件|文件夹|目录|桌面|磁盘|路径|\.\w{1,8}\b|yaml|json|markdown|md文档)", contextual) and action:
        if _matches(r"(?:找|查|搜|定位|哪里|在哪)", current):
            add("search", "file_search_request")
        add("filesystem_read", "filesystem_read_request")
        if _matches(r"(?:修改|改一下|编辑|写入|保存|新建|创建|移动|重命名)", current):
            add("filesystem_write", "filesystem_write_request")
    if _matches(r"(?:网页|网站|网址|链接|https?://|上网|在线)", contextual) and action:
        add("web", "web_access_request")
    if _matches(r"(?:现在|当前|当地|北京时间|今天).{0,8}(?:几点|时间|几号|星期几)|(?:几点了|当前时间|时区转换)", current):
        add("time", "time_request")
    if _matches(r"(?:算一下|计算|等于多少|\d\s*[-+*/%^]\s*\d)", current):
        add("calculator", "calculation_request")
    if _matches(r"(?:life\s*hud|铁幕)", current) and _matches(r"(?:帮我|请|看看|查看|读取|查|记录|数据|状态|打开|执行|开始|结束)", current):
        add("lifehud", "lifehud_access_request")
    if _matches(r"(?:回显|echo)", current):
        add("echo", "echo_request")
    return tuple(groups), tuple(reasons)


def resolve_tool_context(
    user_message: str,
    recent_context: Sequence[str] | str | None,
    registry: ToolRegistry,
    *,
    mode: str = "dynamic",
) -> ToolContext:
    """Return schemas visible to the model without changing the registry."""
    if mode not in {"dynamic", "all"}:
        raise ValueError(f"unsupported tool router mode: {mode}")
    tools = registry.list()
    by_name = {tool.name: tool for tool in tools}
    all_schemas = [tool.schema() for tool in tools]
    persistent = tuple(name for name in PERSISTENT_CORE if name in by_name)
    if mode == "all":
        return ToolContext(
            mode=mode, persistent_tools=persistent, dynamic_groups=("all",),
            exposed_tools=tuple(by_name), reason_tags=("all_mode",), schemas=tuple(all_schemas),
            registered_tools_count=len(tools), registered_schema_chars=_schema_chars(all_schemas),
        )
    groups, reasons = _dynamic_groups(user_message, recent_context)
    names = list(persistent)
    for group in groups:
        names.extend(name for name in TOOL_GROUPS[group] if name in by_name and name not in names)
    schemas = [by_name[name].schema() for name in names]
    return ToolContext(
        mode=mode, persistent_tools=persistent, dynamic_groups=groups,
        exposed_tools=tuple(names), reason_tags=reasons, schemas=tuple(schemas),
        registered_tools_count=len(tools), registered_schema_chars=_schema_chars(all_schemas),
    )


def safe_resolve_tool_context(
    user_message: str,
    recent_context: Sequence[str] | str | None,
    registry: ToolRegistry,
    *,
    mode: str = "dynamic",
) -> ToolContext:
    """Fail closed to persistent memory tools, never to an empty accidental selection."""
    try:
        return resolve_tool_context(user_message, recent_context, registry, mode=mode)
    except Exception:
        tools = registry.list()
        by_name = {tool.name: tool for tool in tools}
        all_schemas = [tool.schema() for tool in tools]
        names = tuple(name for name in PERSISTENT_CORE if name in by_name)
        schemas = tuple(by_name[name].schema() for name in names)
        return ToolContext(
            mode=mode, persistent_tools=names, dynamic_groups=(), exposed_tools=names,
            reason_tags=("router_error_persistent_fallback",), schemas=schemas,
            registered_tools_count=len(tools), registered_schema_chars=_schema_chars(all_schemas),
            fallback=True,
        )
