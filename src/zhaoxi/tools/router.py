"""Deterministic per-turn selection of tool schemas."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from zhaoxi.tools.registry import ToolRegistry


from zhaoxi.tools.metadata import PERSISTENT_CORE, TOOL_GROUPS
from zhaoxi.tools.manifest import is_action_request, resolve_capability


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
        semantic_reasons = [reason for reason in self.reason_tags if not reason.startswith("force:")]
        semantic_matched = bool(self.dynamic_groups and self.dynamic_groups != ("all",))
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
            "semantic_route_matched": semantic_matched,
            "semantic_route_groups": list(self.dynamic_groups) if semantic_matched else [],
            "semantic_route_reason": ",".join(semantic_reasons) if semantic_matched else "",
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
    if _matches(r"(?:还记得|记不记得|之前聊过|上次那|以前记过|回忆一下|查.*记忆|(?:之前|以前|上次).{0,16}(?:怎么说|说过|提过|讲过).{0,8}(?:来着|吗|呢)?)", current):
        add("memory_search", "memory_recall_request")
    if _matches(r"(?:置顶|固定|忘掉|忘记这|删除.*记忆|归档.*记忆|恢复.*记忆|重新激活.*记忆|整理.*记忆|合并.*记忆)", current):
        add("memory_admin", "memory_management_request")
    if _matches(r"(?:潮庭|archive|档案库)", current) and action:
        add("archive", "archive_access_request")
    file_subject = _matches(r"(?:文件|文件夹|目录|桌面|磁盘|路径|复盘|笔记|报告|文档|\.\w{1,8}\b|yaml|json|markdown|md文档)", contextual)
    if file_subject and action:
        if _matches(r"(?:找|查|搜|定位|哪里|在哪)", current):
            add("local_search", "file_search_request")
        add("filesystem_read", "filesystem_read_request")
        if _matches(r"(?:修改|改一下|编辑|写入|保存|新建|创建|移动|重命名)", current):
            add("filesystem_write", "filesystem_write_request")
    if _matches(r"(?:网页|网站|网址|链接|https?://|上网|在线)", contextual) and action:
        add("web", "web_access_request")
    if _matches(r"(?:现在|当前|当地|北京时间|今天).{0,8}(?:几点|时间|几号|星期几)|(?:几点了|当前时间|时区转换)", current):
        add("time", "time_request")
    if _matches(r"(?:算一下|计算|等于多少|\d\s*[-+*/%^]\s*\d)", current):
        add("calculator", "calculation_request")
    lifehud_named = _matches(r"(?:life\s*hud|铁幕)", current)
    life_domain = _matches(
        r"(?:吃(?:了|得|过|的)?什么|吃得|饮食|睡眠|睡得|做过什么|任务.{0,6}(?:完成|进度|情况)|focus\s*session|能量|经验|生活状态)",
        current,
    )
    life_query = _matches(r"(?:帮我|请|看看|查看|读取|查询|查一下|记录|数据|状态|评价|评估|怎么样|如何|多少|完成情况|做过什么)", current)
    if life_query and (lifehud_named or life_domain):
        reason = "daily_diet_query" if _matches(r"(?:吃|饮食)", current) else "lifehud_natural_language_query"
        add("lifehud", reason)
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
    manifest = registry.manifest()
    usable = {t["name"] for t in manifest if t["enabled"] and t["available"]}
    persistent = tuple(t["name"] for t in manifest if t["persistent"] and t["name"] in usable)
    forced = [t["name"] for t in manifest if t["force_expose"] and t["name"] in usable]
    if mode == "all":
        return ToolContext(
            mode=mode, persistent_tools=persistent, dynamic_groups=("all",),
            exposed_tools=tuple(name for name in by_name if name in usable), reason_tags=("all_mode",), schemas=tuple(by_name[name].schema() for name in by_name if name in usable),
            registered_tools_count=len(tools), registered_schema_chars=_schema_chars(all_schemas),
        )
    groups, reasons = _dynamic_groups(user_message, recent_context)
    if is_action_request(user_message):
        resolved = resolve_capability(user_message, manifest)["groups"]
        for group in resolved:
            if group not in groups:
                groups = (*groups, group)
                reasons = (*reasons, "manifest_capability_match")
    usable_groups = {t["group"] for t in manifest if t["enabled"] and t["available"]}
    selected = [
        (group, reason)
        for group, reason in zip(groups, reasons)
        if group in usable_groups or (group == "memory_search" and "memory_core" in usable_groups)
    ]
    groups = tuple(group for group, _ in selected)
    reasons = tuple(reason for _, reason in selected)
    names = list(dict.fromkeys((*persistent, *forced)))
    for group in groups:
        names.extend(t["name"] for t in manifest if t["group"] == group and t["name"] in usable and t["name"] not in names)
    normal = {t["name"] for t in manifest if t["persistent"] or t["group"] in groups}
    reasons = (*reasons, *("force:" + name for name in forced if name not in normal))
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
        names = tuple(t["name"] for t in registry.manifest() if (t["persistent"] or t["force_expose"]) and t["enabled"] and t["available"])
        schemas = tuple(by_name[name].schema() for name in names)
        return ToolContext(
            mode=mode, persistent_tools=names, dynamic_groups=(), exposed_tools=names,
            reason_tags=("router_error_persistent_fallback",), schemas=schemas,
            registered_tools_count=len(tools), registered_schema_chars=_schema_chars(all_schemas),
            fallback=True,
        )
