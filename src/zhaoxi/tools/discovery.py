"""Small capability catalog and turn-scoped schema expansion."""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from zhaoxi.tools.base import Tool, ToolResult
from zhaoxi.tools.registry import ToolRegistry
from zhaoxi.tools.router import ToolContext
from zhaoxi.tools.manifest import group_inventory, inventory_summary, resolve_capability


class RequestToolGroupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_.:-]+$", json_schema_extra={"not": {"const": "all"}})


class RequestToolGroupTool(Tool):
    name = "request_tool_group"
    description = "当前手边的钥匙不足时，从钥匙柜请求一个能力组，加载后继续原任务；已在手边的钥匙直接使用。"
    input_model = RequestToolGroupInput

    async def execute(self, arguments: RequestToolGroupInput) -> ToolResult:
        return ToolResult(success=False, content="能力扩展需要当前对话的执行上下文。", error="no_turn_context")


class InspectToolCatalogInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["summary", "list_groups", "list_tools", "inspect_group", "inspect_tool", "resolve"] = "summary"
    group: str | None = None
    name: str | None = None
    need: str | None = Field(default=None, max_length=2000)


class InspectToolCatalogTool(Tool):
    name = "inspect_tool_catalog"
    description = "查询完整钥匙柜数量、分组或具体钥匙状态；resolve 动作根据 need 解析任务所需能力组，然后用 request_tool_group 取得钥匙。查询目录不等于执行业务。"
    input_model = InspectToolCatalogInput

    async def execute(self, arguments: InspectToolCatalogInput) -> ToolResult:
        return ToolResult(success=False, content="目录查询需要当前对话上下文。", error="no_turn_context")


@dataclass
class ToolDiscoveryState:
    initial: ToolContext
    requested: list[str] = field(default_factory=list)
    expanded: list[str] = field(default_factory=list)
    expansion_count: int = 0
    business_tool_called: bool = False
    resolution_checked: bool = False

    def known(self, registry: ToolRegistry) -> list[str]:
        return [group["group"] for group in group_inventory(registry.manifest())]

    def schemas(self, registry: ToolRegistry) -> list[dict]:
        manifest = registry.manifest()
        initially_forced = set(self.initial.reason_tags)  # force-only names are not permanent selections
        names = set(self.initial.exposed_tools) | set(self.expanded)
        names -= {tag.removeprefix("force:") for tag in initially_forced if tag.startswith("force:")}
        names.update(t["name"] for t in manifest if t["persistent"] or t["force_expose"])
        usable = {t["name"] for t in manifest if t["enabled"] and t["available"]}
        return [tool.schema() for tool in registry.list() if tool.name in names and tool.name in usable]

    def inspect(self, arguments: dict, registry: ToolRegistry) -> ToolResult:
        try:
            query = InspectToolCatalogInput.model_validate(arguments)
        except ValidationError:
            return ToolResult(success=False, content="钥匙柜查询参数无效。", error="invalid_catalog_query")
        manifest = registry.manifest([s["function"]["name"] for s in self.schemas(registry)])
        if query.action == "summary":
            data = inventory_summary(manifest)
        elif query.action == "list_groups":
            data = group_inventory(manifest)
        elif query.action == "list_tools":
            data = manifest
        elif query.action == "resolve" and query.need:
            data = resolve_capability(query.need, manifest)
        elif query.action == "inspect_group" and query.group:
            group = "memory_core" if query.group == "memory_search" else query.group
            data = [t for t in manifest if t["group"] == group]
        elif query.action == "inspect_tool" and query.name:
            data = next((t for t in manifest if t["name"] == query.name), None)
        else:
            return ToolResult(success=False, content="请提供该查询需要的 group、name 或 need。", error="invalid_catalog_query")
        self.resolution_checked = True
        return ToolResult(success=True, content="钥匙柜实时查询完成；这不是业务执行结果。", data=data)

    def request(self, arguments: dict, registry: ToolRegistry) -> ToolResult:
        try:
            group = RequestToolGroupInput.model_validate(arguments).group
            if group == "all":
                raise ValueError("all is prohibited")
        except (ValidationError, ValueError):
            return ToolResult(success=False, content="无效的钥匙组，请从能力目录选择；不能请求 all。", error="invalid_group")
        group = "memory_core" if group == "memory_search" else group
        self.resolution_checked = True
        if group not in self.requested:
            self.requested.append(group)
        manifest = registry.manifest()
        names = [t["name"] for t in manifest if t["group"] == group and t["enabled"] and t["available"]]
        if not names:
            return ToolResult(success=False, content="该能力未注册、已停用或依赖不可用，请查询钥匙柜状态。", error="unavailable_group")
        exposed = {s["function"]["name"] for s in self.schemas(registry)}
        additions = [name for name in names if name not in exposed]
        if not additions:
            return ToolResult(success=True, content="这组钥匙已在手边，请直接使用。", data={"group": group, "tools": names})
        if self.expansion_count >= 2:
            return ToolResult(success=False, content="本轮已达到两次能力扩展上限，请使用现有能力或如实说明限制。", error="expansion_limit")
        self.expansion_count += 1
        self.expanded.extend(additions)
        return ToolResult(success=True, content="钥匙已加载，请继续原任务；加载本身尚未完成业务查询。", data={"group": group, "tools": names})

    def catalog(self, registry: ToolRegistry) -> str:
        groups = group_inventory(registry.manifest())
        return (
            "\n\n钥匙柜（实时能力目录）：\n"
            + "\n".join(f"- {g['group']}: {g['summary']}（{g['usable']}/{g['registered']} 可用"
                         + ("，已停用" if not g['enabled'] else "，依赖不可用" if not g['usable'] else "") + "）" for g in groups)
            + f"\nregistered_tools={len(registry.list())}；exposed_tools={len(self.schemas(registry))}。"
            + "手边数量不是全部能力。总数、完整列表及状态请查询 inspect_tool_catalog。"
            + "任务能力不清时用 inspect_tool_catalog(action=resolve, need=任务需求) 解析，再 request_tool_group。"
            + "已有钥匙直接使用；每轮最多扩展两次，不允许 all；查询目录和取得钥匙不等于完成任务。"
        )

    def diagnostics(self, registry: ToolRegistry) -> dict:
        import json
        schemas = self.schemas(registry)
        final = [schema["function"]["name"] for schema in schemas]
        manifest = registry.manifest(final)
        summary = inventory_summary(manifest)
        return {
            **self.initial.diagnostics(),
            "known_capabilities": self.known(registry),
            "known_capability_groups": self.known(registry),
            "registered_tools_count": summary["registered_tools"],
            "enabled_tools_count": summary["enabled_tools"],
            "available_tools_count": summary["available_tools"],
            "router_matched_groups": list(self.initial.dynamic_groups),
            "initial_exposed_tools": list(self.initial.exposed_tools),
            "requested_tool_groups": list(self.requested),
            "expanded_tools": list(self.expanded),
            "force_exposed_tools": [t["name"] for t in manifest if t["force_expose"] and t["exposed"]],
            "persistent_tools": [t["name"] for t in manifest if t["persistent"] and t["exposed"]],
            "capability_expansion_count": self.expansion_count,
            "final_exposed_tools": final,
            "total_exposed_tools_count": len(final),
            "total_registered_tools_count": len(manifest),
            "filtered_tools_count": len(manifest) - len(final),
            "dynamic_tools_count": sum(not t["persistent"] and t["exposed"] for t in manifest),
            "tool_schema_chars": len(json.dumps(schemas, ensure_ascii=False, separators=(",", ":"))),
        }
