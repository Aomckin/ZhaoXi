"""Tools for conservative working-note maintenance."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from zhaoxi.permission.models import PermissionLevel, SideEffect
from zhaoxi.tools.base import Tool, ToolResult
from zhaoxi.working_notes.models import NoteConfidence, NoteSource, NoteType
from zhaoxi.working_notes.service import WorkingNotesService


class NotesAddInput(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    type: NoteType
    content: str = Field(min_length=1, max_length=4000)
    source: NoteSource
    confidence: NoteConfidence
    expires_at: datetime | None = None
    related_project: str | None = Field(default=None, max_length=200)
    related_task: str | None = Field(default=None, max_length=200)


class NotesUpdateInput(BaseModel):
    note_id: str
    topic: str | None = Field(default=None, min_length=1, max_length=200)
    type: NoteType | None = None
    content: str | None = Field(default=None, min_length=1, max_length=4000)
    source: NoteSource | None = None
    confidence: NoteConfidence | None = None
    expires_at: datetime | None = None
    related_project: str | None = Field(default=None, max_length=200)
    related_task: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_dump(exclude={"note_id"}, exclude_none=True):
            raise ValueError("至少提供一个更新字段")
        return self


class NotesIdInput(BaseModel):
    note_id: str


class NotesListInput(BaseModel):
    filter: Literal["active", "resolved", "expired", "all_recent"] = "active"


class EmptyInput(BaseModel):
    pass


def public(note) -> dict[str, Any]:
    return note.model_dump(mode="json")


class NotesTool(Tool):
    group = "working_notes"

    def __init__(self, service: WorkingNotesService) -> None:
        self.service = service


class NotesAddTool(NotesTool):
    name = "notes_add"
    description = "保守记录近期工作现场。仅用于持续工作、明确待办/卡点/决定；普通闲聊不要写。模型归纳用 source=assistant/confidence=working，模型推测必须 type=hypothesis/confidence=tentative，不能冒充用户确认事实。"
    input_model = NotesAddInput
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.LOCAL_STATE})
    default_confirm_write = False

    async def execute(self, arguments: NotesAddInput) -> ToolResult:
        note, created = self.service.add(**arguments.model_dump())
        return ToolResult(success=True, content="已贴上近期工作便签。" if created else "相近便签已更新。",
                          data={"note": public(note), "created": created})


class NotesUpdateTool(NotesTool):
    name = "notes_update"
    description = "按 note_id 更新近期工作便签，并保留来源与可信度边界。"
    input_model = NotesUpdateInput
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.LOCAL_STATE})
    default_confirm_write = False

    async def execute(self, arguments: NotesUpdateInput) -> ToolResult:
        values = arguments.model_dump(exclude={"note_id"}, exclude_none=True)
        return ToolResult(success=True, content="便签已更新。", data=public(self.service.update(arguments.note_id, **values)))


class NotesResolveTool(NotesTool):
    name = "notes_resolve"
    description = "按 note_id 将近期工作便签标记为已解决，使其退出常驻上下文。"
    input_model = NotesIdInput
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.LOCAL_STATE})
    default_confirm_write = False

    async def execute(self, arguments: NotesIdInput) -> ToolResult:
        return ToolResult(success=True, content="便签已解决。", data=public(self.service.resolve(arguments.note_id)))


class NotesDeleteTool(NotesTool):
    name = "notes_delete"
    description = "按 note_id 永久删除短期工作便签。"
    input_model = NotesIdInput
    permission = PermissionLevel.DELETE
    side_effects = frozenset({SideEffect.DATA_DELETION})

    async def execute(self, arguments: NotesIdInput) -> ToolResult:
        self.service.delete(arguments.note_id)
        return ToolResult(success=True, content="便签已删除。", data={"note_id": arguments.note_id})


class NotesListTool(NotesTool):
    name = "notes_list"
    description = "查询近期工作便签及 note_id，支持 active/resolved/expired/all_recent。"
    input_model = NotesListInput

    async def execute(self, arguments: NotesListInput) -> ToolResult:
        notes = self.service.list(arguments.filter)
        return ToolResult(success=True, content=f"找到 {len(notes)} 条工作便签。", data=[public(note) for note in notes])


class NotesSnapshotTool(NotesTool):
    name = "notes_snapshot"
    description = "读取每轮上下文所使用的短 Working Notes Snapshot。"
    input_model = EmptyInput

    async def execute(self, arguments: EmptyInput) -> ToolResult:
        value = self.service.snapshot()
        return ToolResult(success=True, content=value, data={"snapshot": value})


def create_working_notes_tools(service: WorkingNotesService) -> list[Tool]:
    return [NotesAddTool(service), NotesUpdateTool(service), NotesResolveTool(service),
            NotesDeleteTool(service), NotesListTool(service), NotesSnapshotTool(service)]
