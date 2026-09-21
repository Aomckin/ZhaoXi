"""Tools exposing controlled long-term memory operations to the model."""

from typing import Any

from pydantic import BaseModel, Field

from zhaoxi.memory.models import MemoryCreate, MemoryKind, MemoryQuery, MemoryStatus, MemoryUpdate
from zhaoxi.memory.service import MemoryService
from zhaoxi.permission.models import PermissionLevel, SideEffect
from zhaoxi.tools.base import Tool, ToolResult


class RememberInput(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    kind: MemoryKind = MemoryKind.SEMANTIC
    tags: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0, le=1)
    supersedes_id: str | None = None
    importance: float = Field(default=0.9, ge=0, le=1)
    activation: float = Field(default=0.7, ge=0, le=1)
    pinned: bool = False


class SearchMemoryInput(BaseModel):
    query: str = ""
    kind: MemoryKind | None = None
    tags: list[str] = Field(default_factory=list)
    limit: int = Field(default=10, ge=1, le=50)
    statuses: list[MemoryStatus] = Field(default_factory=lambda: [MemoryStatus.ACTIVE])


class UpdateMemoryInput(BaseModel):
    memory_id: str
    content: str | None = None
    kind: MemoryKind | None = None
    tags: list[str] | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    importance: float | None = Field(default=None, ge=0, le=1)
    activation: float | None = Field(default=None, ge=0, le=1)
    pinned: bool | None = None


class ForgetMemoryInput(BaseModel):
    memory_id: str


class LifecycleMemoryInput(BaseModel):
    memory_id: str


class PinMemoryInput(BaseModel):
    memory_id: str
    pinned: bool = True


class ConsolidateMemoriesInput(BaseModel):
    memory_ids: list[str] = Field(min_length=2)
    content: str = Field(min_length=1, max_length=20_000)
    tags: list[str] = Field(default_factory=list)


def public_record(record: Any) -> dict[str, Any]:
    return record.model_dump(mode="json", exclude={"normalized_content", "metadata"})


class RememberMemoryTool(Tool):
    name = "remember_memory"
    description = "记录值得保留的生活记忆并返回记忆 ID。可根据对话自主记录日常小事、偏好、近期变化、阶段性事件、习惯及关系信息，无需等待用户说“记住”，不要默认忽略琐事；遵守用户禁止记忆的要求。"
    input_model = RememberInput
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.LOCAL_STATE})
    default_confirm_write = False

    def __init__(self, service: MemoryService) -> None:
        self.service = service

    def confirmation_description(self, arguments: dict[str, Any]) -> str:
        return "朝汐想记录一条长期记忆"

    async def execute(self, arguments: RememberInput) -> ToolResult:
        result = await self.service.remember(MemoryCreate(**arguments.model_dump()))
        candidates = [public_record(item) for item in result.conflict_candidates]
        if candidates and not result.created:
            content = "发现可能重复或冲突的记忆，尚未保存；请先向用户确认是否替换。"
        elif result.duplicate:
            content = "该信息已存在。"
        else:
            content = "已保存长期记忆。"
        return ToolResult(
            success=True,
            content=content,
            data={
                "memory": public_record(result.record),
                "created": result.created,
                "duplicate": result.duplicate,
                "conflict_candidates": candidates,
            },
        )


class SearchMemoriesTool(Tool):
    name = "search_memories"
    description = "搜索朝汐的长期记忆，返回内容、记忆 ID、时间和来源。话题与过去经历、偏好、人物、地点、计划或近期事件自然相关，且可能改善当前对话时可主动检索；不要为了展示记忆能力而频繁检索。"
    input_model = SearchMemoryInput

    def __init__(self, service: MemoryService) -> None:
        self.service = service

    async def execute(self, arguments: SearchMemoryInput) -> ToolResult:
        results = await self.service.search(
            MemoryQuery(
                text=arguments.query,
                kind=arguments.kind,
                tags=arguments.tags,
                limit=arguments.limit,
                statuses=arguments.statuses,
            )
        )
        return ToolResult(
            success=True,
            content=f"找到 {len(results)} 条长期记忆。",
            data=[
                {**public_record(item.record), "score": item.score, "match_reason": item.match_reason}
                for item in results
            ],
        )


class UpdateMemoryTool(Tool):
    name = "update_memory"
    description = "按记忆 ID 修正一条长期记忆。用户自然修正、补充或改变已有信息时可更新，无需明确说“更新记忆”；目标或含义不清时先核实。"
    input_model = UpdateMemoryInput
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.LOCAL_STATE})
    default_confirm_write = False

    def __init__(self, service: MemoryService) -> None:
        self.service = service

    def confirmation_description(self, arguments: dict[str, Any]) -> str:
        return "朝汐想更新一条已有记忆"

    async def execute(self, arguments: UpdateMemoryInput) -> ToolResult:
        values = arguments.model_dump(exclude={"memory_id"}, exclude_none=True)
        record = await self.service.update(arguments.memory_id, MemoryUpdate(**values))
        return ToolResult(success=True, content="记忆已更新。", data=public_record(record))


class ForgetMemoryTool(Tool):
    name = "forget_memory"
    description = "按记忆 ID 遗忘长期记忆；遗忘后它不会再被正常检索或注入上下文。"
    input_model = ForgetMemoryInput
    permission = PermissionLevel.DELETE
    side_effects = frozenset({SideEffect.DATA_DELETION})

    def __init__(self, service: MemoryService) -> None:
        self.service = service

    async def execute(self, arguments: ForgetMemoryInput) -> ToolResult:
        record = await self.service.forget(arguments.memory_id)
        return ToolResult(success=True, content="已遗忘该记忆。", data=public_record(record))


class ArchiveMemoryTool(Tool):
    name = "archive_memory"
    description = "将不再活跃但仍有历史价值的长期记忆归档；Pinned 记忆不会被自动归档。"
    input_model = LifecycleMemoryInput
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.LOCAL_STATE})

    def __init__(self, service: MemoryService) -> None:
        self.service = service

    async def execute(self, arguments: LifecycleMemoryInput) -> ToolResult:
        record = await self.service.archive(arguments.memory_id)
        content = "Pinned 记忆不会被归档。" if record.pinned else "记忆已归档。"
        return ToolResult(success=True, content=content, data=public_record(record))


class ReactivateMemoryTool(Tool):
    name = "reactivate_memory"
    description = "重新激活一条 COLD、DORMANT 或 ARCHIVED 记忆并提高其 activation。"
    input_model = LifecycleMemoryInput
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.LOCAL_STATE})

    def __init__(self, service: MemoryService) -> None:
        self.service = service

    async def execute(self, arguments: LifecycleMemoryInput) -> ToolResult:
        record = await self.service.reactivate(arguments.memory_id)
        return ToolResult(success=True, content="记忆已重新激活。", data=public_record(record))


class PinMemoryTool(Tool):
    name = "pin_memory"
    description = "固定或取消固定关键长期记忆；Pinned 记忆不参与自动遗忘。"
    input_model = PinMemoryInput
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.LOCAL_STATE})

    def __init__(self, service: MemoryService) -> None:
        self.service = service

    async def execute(self, arguments: PinMemoryInput) -> ToolResult:
        record = await self.service.set_pinned(arguments.memory_id, arguments.pinned)
        return ToolResult(success=True, content="记忆固定状态已更新。", data=public_record(record))


class ConsolidateMemoriesTool(Tool):
    name = "consolidate_memories"
    description = "从至少两条相关经历归纳一条可追溯 Semantic Memory，并保留原始 Episode。"
    input_model = ConsolidateMemoriesInput
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.LOCAL_STATE})

    def __init__(self, service: MemoryService) -> None:
        self.service = service

    async def execute(self, arguments: ConsolidateMemoriesInput) -> ToolResult:
        record = await self.service.consolidate(
            arguments.memory_ids, arguments.content, tags=arguments.tags
        )
        return ToolResult(success=True, content="相关记忆已压缩整合。", data=public_record(record))


def create_memory_tools(service: MemoryService) -> list[Tool]:
    return [
        RememberMemoryTool(service),
        SearchMemoriesTool(service),
        UpdateMemoryTool(service),
        ForgetMemoryTool(service),
        ArchiveMemoryTool(service),
        ReactivateMemoryTool(service),
        PinMemoryTool(service),
        ConsolidateMemoriesTool(service),
    ]
