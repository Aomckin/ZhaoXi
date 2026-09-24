"""Registry-derived tool inventory, capability matching and durable overrides."""

import json
import re
from pathlib import Path
from threading import RLock

from zhaoxi.permission.models import PermissionLevel, SideEffect
from zhaoxi.tools.metadata import (
    GROUP_LABELS, PERSISTENT_CORE, TOOL_GROUPS, TOOL_LABELS, TOOL_USAGE,
)
from zhaoxi.tools.base import Tool


class ToolControl:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.lock = RLock()
        self.overrides: dict[str, dict] = {}
        if self.path and self.path.exists():
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or any(
                not isinstance(v, dict) or any(
                    (not isinstance(b, dict) or any(not isinstance(n, str) or type(flag) is not bool for n, flag in b.items()))
                    if k == "capabilities" else
                    (k not in {"enabled", "force_expose", "confirm_write"} or type(b) is not bool)
                    for k, b in v.items()
                )
                for v in value.values()
            ):
                raise ValueError("无效的 Tool Override 配置")
            self.overrides = value

    def update(self, names, *, enabled=None, force_expose=None, confirm_write=None, reset=False):
        with self.lock:
            updated = {name: dict(value) for name, value in self.overrides.items()}
            for name in names:
                if reset:
                    updated.pop(name, None)
                else:
                    value = updated.setdefault(name, {})
                    for key, setting in (("enabled", enabled), ("force_expose", force_expose), ("confirm_write", confirm_write)):
                        if setting is not None:
                            if type(setting) is not bool:
                                raise ValueError("Tool 开关必须为布尔值")
                            value[key] = setting
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_suffix(".tmp")
                temporary.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
                temporary.replace(self.path)
            self.overrides = updated

    def update_capability(self, name: str, capability: str, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise ValueError("Tool 能力组开关必须为布尔值")
        with self.lock:
            updated = {key: {**value, **({"capabilities": dict(value["capabilities"])}
                                      if "capabilities" in value else {})}
                       for key, value in self.overrides.items()}
            updated.setdefault(name, {}).setdefault("capabilities", {})[capability] = enabled
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_suffix(".tmp")
                temporary.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
                temporary.replace(self.path)
            self.overrides = updated


def tool_metadata(tool, source: str, override: dict, exposed: set[str]) -> dict:
    group = getattr(tool, "group", None)
    if not group:
        group = "memory_core" if tool.name in TOOL_GROUPS["memory_core"] else next(
            (group for group, names in TOOL_GROUPS.items() if tool.name in names),
            source.replace(":", "_") if source != "builtin" else "other",
        )
    try:
        availability = getattr(tool, "available", True)
        available = bool(availability() if callable(availability) else availability)
    except Exception:
        available = False
    enabled = override.get("enabled", getattr(tool, "default_enabled", True))
    write_capable = (
        tool.permission == PermissionLevel.WRITE
        or type(tool).permission_for is not Tool.permission_for
    )
    raw_summary = getattr(tool, "summary", tool.description.split("。", 1)[0])
    capability_reader = getattr(tool, "capability_flags", None)
    return {
        "name": tool.name, "group": group, "source": source,
        "display_name": TOOL_LABELS.get(tool.name, tool.name),
        "summary": raw_summary,
        "usage": TOOL_USAGE.get(tool.name, str(raw_summary).removeprefix(f"[{source}] ")[:160]),
        "registered": True, "enabled": enabled, "available": available,
        "persistent": getattr(tool, "persistent", tool.name in PERSISTENT_CORE),
        "force_expose": override.get("force_expose", False),
        "confirm_write": override.get("confirm_write", getattr(tool, "default_confirm_write", True)),
        "write_capable": write_capable,
        "capabilities": capability_reader() if callable(capability_reader) else {},
        "exposed": tool.name in exposed and enabled and available,
        "read_only": type(tool).permission_for is Tool.permission_for and tool.permission == PermissionLevel.READ and tool.side_effects == frozenset({SideEffect.NONE}),
        "destructive": tool.permission in {PermissionLevel.DELETE, PermissionLevel.DANGEROUS} or SideEffect.DATA_DELETION in tool.side_effects,
        "aliases": list(getattr(tool, "aliases", ())), "intents": list(getattr(tool, "intents", ())),
    }


def group_inventory(manifest: list[dict]) -> list[dict]:
    groups = {}
    for item in manifest:
        group = groups.setdefault(item["group"], {
            "group": item["group"], "summary": GROUP_LABELS.get(item["group"], item["group"]),
            "registered": 0, "enabled": 0, "available": 0, "usable": 0,
        })
        group["registered"] += 1
        group["enabled"] += int(item["enabled"])
        group["available"] += int(item["available"])
        group["usable"] += int(item["enabled"] and item["available"])
    return list(groups.values())


def inventory_summary(manifest: list[dict]) -> dict:
    return {
        "registered_tools": len(manifest), "enabled_tools": sum(t["enabled"] for t in manifest),
        "available_tools": sum(t["available"] for t in manifest),
        "currently_exposed": sum(t["exposed"] for t in manifest),
        "groups": len(group_inventory(manifest)),
    }


def resolve_capability(need: str, manifest: list[dict]) -> dict:
    """Match metadata plus a small set of domain aliases, without an LLM."""
    text = need.casefold()
    aliases = {
        "memory_core": ("记忆", "回忆", "记住"), "memory_admin": ("遗忘", "整理记忆", "固定记忆"),
        "archive": ("潮庭", "档案", "书库"), "local_search": ("本地", "桌面", "电脑", "找文件", "搜索文件"),
        "filesystem_read": ("文件", "目录", "桌面", "读取"),
        "filesystem_write": ("修改文件", "写入", "移动文件", "编辑文件", "新建"),
        "web": ("网页", "网站", "网址", "链接", "http://", "https://"),
        "time": ("几点", "时间", "时区"), "calculator": ("计算", "算一下"),
        "lifehud": ("lifehud", "life hud", "铁幕"),
        "expression": ("保存表情", "收藏表情", "收进表情包"),
        "agenda": ("日程", "安排", "主线", "截止", "deadline", "面试", "宣讲", "做完了", "不去了"),
    }
    matched = []
    for tool in manifest:
        phrases = [tool["name"], tool["group"], tool["summary"], *tool["aliases"], *tool["intents"], *aliases.get(tool["group"], ())]
        if any(str(p).casefold() in text for p in phrases if p):
            matched.append(tool)
    groups = list(dict.fromkeys(t["group"] for t in matched if t["enabled"] and t["available"]))
    return {
        "matched": bool(groups), "groups": groups,
        "unavailable_groups": list(dict.fromkeys(t["group"] for t in matched if not (t["enabled"] and t["available"]) and t["group"] not in groups)),
    }


def is_action_request(text: str) -> bool:
    return bool(re.search(r"帮我|请.*(?:查|找|读|改|写|发|算|操作|获取|执行)|查一下|找一下|读一下|计算|执行|获取|发送", text))
