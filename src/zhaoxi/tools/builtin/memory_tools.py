"""Tools exposing controlled long-term memory operations to the model."""

from typing import Any

from pydantic import BaseModel, Field

from zhaoxi.memory.models import MemoryCreate, MemoryKind, MemoryQuery, MemoryUpdate
from zhaoxi.memory.service import MemoryService
from zhaoxi.tools.base import Tool, ToolResult


class RememberInput(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    kind: MemoryKind = MemoryKind.SEMANTIC
    tags: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0, le=1)
    supersedes_id: str | None = None


class SearchMemoryInput(BaseModel):
    query: str = ""
    kind: MemoryKind | None = None
    tags: list[str] = Field(default_factory=list)
    limit: int = Field(default=10, ge=1, le=50)


class UpdateMemoryInput(BaseModel):
    memory_id: str
    content: str | None = None
    kind: MemoryKind | None = None
    tags: list[str] | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class ForgetMemoryInput(BaseModel):
    memory_id: str


def public_record(record: Any) -> dict[str, Any]:
    return record.model_dump(mode="json", exclude={"normalized_content", "metadata"})


class RememberMemoryTool(Tool):
    name = "remember_memory"
    description = "仅在用户明确要求记住长期信息时使用。保存事实、偏好或事件并返回记忆 ID。"
    input_model = RememberInput

    def __init__(self, service: MemoryService) -> None:
        self.service = service

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
    description = "搜索朝汐的长期记忆，并返回内容、记忆 ID、记录时间和来源。"
    input_model = SearchMemoryInput

    def __init__(self, service: MemoryService) -> None:
        self.service = service

    async def execute(self, arguments: SearchMemoryInput) -> ToolResult:
        results = await self.service.search(
            MemoryQuery(text=arguments.query, kind=arguments.kind, tags=arguments.tags, limit=arguments.limit)
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
    description = "按记忆 ID 修正一条长期记忆。若用户想用新事实替换旧事实，优先明确确认。"
    input_model = UpdateMemoryInput

    def __init__(self, service: MemoryService) -> None:
        self.service = service

    async def execute(self, arguments: UpdateMemoryInput) -> ToolResult:
        values = arguments.model_dump(exclude={"memory_id"}, exclude_none=True)
        record = await self.service.update(arguments.memory_id, MemoryUpdate(**values))
        return ToolResult(success=True, content="记忆已更新。", data=public_record(record))


class ForgetMemoryTool(Tool):
    name = "forget_memory"
    description = "按记忆 ID 遗忘长期记忆；遗忘后它不会再被正常检索或注入上下文。"
    input_model = ForgetMemoryInput

    def __init__(self, service: MemoryService) -> None:
        self.service = service

    async def execute(self, arguments: ForgetMemoryInput) -> ToolResult:
        record = await self.service.forget(arguments.memory_id)
        return ToolResult(success=True, content="已遗忘该记忆。", data=public_record(record))


def create_memory_tools(service: MemoryService) -> list[Tool]:
    return [
        RememberMemoryTool(service),
        SearchMemoriesTool(service),
        UpdateMemoryTool(service),
        ForgetMemoryTool(service),
    ]
