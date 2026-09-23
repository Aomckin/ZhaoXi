"""Tools for structured agenda operations."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from zhaoxi.agenda.models import AgendaStatus, AgendaType
from zhaoxi.agenda.service import AgendaService
from zhaoxi.permission.models import PermissionLevel, SideEffect
from zhaoxi.tools.base import Tool, ToolResult


class AgendaAddInput(BaseModel):
    type: AgendaType
    title: str = Field(min_length=1, max_length=500)
    start_at: datetime | None = None
    end_at: datetime | None = None
    due_at: datetime | None = None
    priority: int = Field(default=0, ge=0, le=3)
    note: str = Field(default="", max_length=2000)
    source: str = Field(default="user", max_length=40)
    scope: str | None = Field(default=None, max_length=80)
    condition: str | None = Field(default=None, max_length=500)
    secondary: bool = False


class AgendaUpdateInput(BaseModel):
    item_id: str
    title: str | None = Field(default=None, min_length=1, max_length=500)
    start_at: datetime | None = None
    end_at: datetime | None = None
    due_at: datetime | None = None
    priority: int | None = Field(default=None, ge=0, le=3)
    note: str | None = Field(default=None, max_length=2000)
    scope: str | None = Field(default=None, max_length=80)
    condition: str | None = Field(default=None, max_length=500)
    secondary: bool | None = None

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_dump(exclude={"item_id"}, exclude_none=True):
            raise ValueError("至少提供一个更新字段")
        return self


class AgendaIdInput(BaseModel):
    item_id: str


class AgendaListInput(BaseModel):
    filter: Literal["today", "upcoming", "deadline", "active", "completed", "overdue", "all_recent"] = "upcoming"


class EmptyInput(BaseModel):
    pass


def public(item) -> dict[str, Any]:
    return item.model_dump(mode="json")


class AgendaTool(Tool):
    group = "agenda"

    def __init__(self, service: AgendaService) -> None:
        self.service = service


class AgendaAddTool(AgendaTool):
    name = "agenda_add"
    description = "添加近期日程事实。event/window 需要 ISO start_at，deadline 需要 ISO due_at；focus 表示主线，expectation 表示无压力期待。先依据 Agenda 中的 Now 把用户自然时间转换为带时区的绝对时间。"
    input_model = AgendaAddInput
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.LOCAL_STATE})
    default_confirm_write = False

    async def execute(self, arguments: AgendaAddInput) -> ToolResult:
        item, created = self.service.add(**arguments.model_dump())
        return ToolResult(success=True, content="已加入近期日程。" if created else "已有相近日程，已更新。",
                          data={"item": public(item), "created": created})


class AgendaUpdateTool(AgendaTool):
    name = "agenda_update"
    description = "按 item_id 修改已有日程的标题、时间或说明；目标不明确时先用 agenda_list 查询。"
    input_model = AgendaUpdateInput
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.LOCAL_STATE})
    default_confirm_write = False

    async def execute(self, arguments: AgendaUpdateInput) -> ToolResult:
        values = arguments.model_dump(exclude={"item_id"}, exclude_none=True)
        return ToolResult(success=True, content="日程已更新。", data=public(self.service.update(arguments.item_id, **values)))


class AgendaCompleteTool(AgendaTool):
    name = "agenda_complete"
    description = "按 item_id 把近期事项标记为已完成；目标不明确时先查询。"
    input_model = AgendaIdInput
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.LOCAL_STATE})
    default_confirm_write = False

    async def execute(self, arguments: AgendaIdInput) -> ToolResult:
        return ToolResult(success=True, content="事项已完成。", data=public(self.service.complete(arguments.item_id)))


class AgendaCancelTool(AgendaTool):
    name = "agenda_cancel"
    description = "按 item_id 取消近期事项；目标不明确时先查询。"
    input_model = AgendaIdInput
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.LOCAL_STATE})
    default_confirm_write = False

    async def execute(self, arguments: AgendaIdInput) -> ToolResult:
        return ToolResult(success=True, content="事项已取消。", data=public(self.service.cancel(arguments.item_id)))


class AgendaListTool(AgendaTool):
    name = "agenda_list"
    description = "查询近期日程的结构化项目及 item_id，支持 today/upcoming/deadline/active/completed/overdue/all_recent。"
    input_model = AgendaListInput

    async def execute(self, arguments: AgendaListInput) -> ToolResult:
        items = self.service.list(arguments.filter)
        return ToolResult(success=True, content=f"找到 {len(items)} 条近期日程。", data=[public(item) for item in items])


class AgendaSnapshotTool(AgendaTool):
    name = "agenda_snapshot"
    description = "读取每轮上下文所使用的短 Agenda Snapshot。"
    input_model = EmptyInput

    async def execute(self, arguments: EmptyInput) -> ToolResult:
        value = self.service.snapshot()
        return ToolResult(success=True, content=value, data={"snapshot": value})


def create_agenda_tools(service: AgendaService) -> list[Tool]:
    return [AgendaAddTool(service), AgendaUpdateTool(service), AgendaCompleteTool(service),
            AgendaCancelTool(service), AgendaListTool(service), AgendaSnapshotTool(service)]
