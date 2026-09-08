"""The single operation-based Tool exposed by LifeHUD-Tool."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from zhaoxi.sdk import PermissionLevel, SideEffect, Tool, ToolResult

from tools.lifehud_tool.client import LifeHudClient
from tools.lifehud_tool.errors import LifeHudError
from tools.lifehud_tool.models import FocusCompleteInput, FocusStartInput, JournalInput, RecentInput


class LifeHudOperation(StrEnum):
    TODAY = "context.today"
    RECENT = "context.recent"
    STATUS = "context.status"
    FOCUS_CURRENT = "focus.current"
    TASKS = "context.tasks"
    DREAMS = "context.dreams"
    LIFE = "context.life"
    JOURNAL = "context.journal"
    MEDIA = "context.media"
    GROWTH = "context.growth"
    FOCUS_START = "focus.start"
    FOCUS_COMPLETE = "focus.complete"


class LifeHudInput(BaseModel):
    operation: LifeHudOperation
    arguments: dict[str, Any] = Field(default_factory=dict)


class LifeHudTool(Tool):
    name = "lifehud"
    description = (
        "读取或更新 Life HUD 事实源。通过 operation 选择受限能力：context.today/recent/status/"
        "tasks/dreams/life/journal/media/growth、focus.current/start/complete。"
    )
    input_model = LifeHudInput

    def __init__(self, client: LifeHudClient) -> None:
        self.client = client

    @staticmethod
    def _operation(arguments: dict[str, Any]) -> LifeHudOperation:
        return LifeHudOperation(arguments["operation"])

    def permission_for(self, arguments: dict[str, Any]) -> PermissionLevel:
        operation = self._operation(arguments)
        if operation in {LifeHudOperation.FOCUS_START, LifeHudOperation.FOCUS_COMPLETE}:
            return PermissionLevel.WRITE
        return PermissionLevel.READ

    def side_effects_for(self, arguments: dict[str, Any]) -> frozenset[SideEffect]:
        if self.permission_for(arguments) is PermissionLevel.WRITE:
            return frozenset({SideEffect.EXTERNAL_SERVICE_WRITE})
        return frozenset({SideEffect.NONE})

    def safe_to_replay(self, arguments: dict[str, Any]) -> bool:
        return self.permission_for(arguments) is PermissionLevel.READ

    def resource_scope(self, arguments: dict[str, Any]) -> str:
        operation = self._operation(arguments)
        payload = arguments.get("arguments", {})
        if operation is LifeHudOperation.FOCUS_START:
            return "lifehud.focus:new:iron_curtain"
        if operation is LifeHudOperation.FOCUS_COMPLETE:
            return f"lifehud.focus:{payload.get('session_id', 'unknown')}"
        return f"lifehud:{operation.value}"

    def confirmation_description(self, arguments: dict[str, Any]) -> str:
        operation = self._operation(arguments)
        if operation is LifeHudOperation.FOCUS_START:
            return "在 Life HUD 中开启铁幕 Focus"
        if operation is LifeHudOperation.FOCUS_COMPLETE:
            return "在 Life HUD 中结束铁幕 Focus"
        return self.description.split("。", 1)[0]

    def _error(self, exc: LifeHudError) -> ToolResult:
        return ToolResult(
            success=False,
            content=str(exc),
            error=exc.code,
            metadata={
                "retryable": exc.retryable,
                "safe_to_replay": False,
                "fact_source": "lifehud",
            },
        )

    def _success(self, value, operation: LifeHudOperation, *, content: str) -> ToolResult:
        return ToolResult(
            success=True,
            content=content,
            data=self.client.dump_for_display(value),
            metadata={
                "fact_source": "lifehud",
                "operation": operation.value,
                "requeryable": self.permission_for({"operation": operation.value}) is PermissionLevel.READ,
                "display_timezone": self.client.display_timezone,
            },
        )

    async def execute(self, arguments: LifeHudInput) -> ToolResult:
        operation = arguments.operation
        payload = arguments.arguments
        try:
            if operation is LifeHudOperation.TODAY:
                value = await self.client.today()
            elif operation is LifeHudOperation.RECENT:
                value = await self.client.recent(RecentInput.model_validate(payload).days)
            elif operation is LifeHudOperation.STATUS:
                value = await self.client.status()
            elif operation is LifeHudOperation.FOCUS_CURRENT:
                value = await self.client.focus()
            elif operation is LifeHudOperation.TASKS:
                value = await self.client.tasks()
            elif operation is LifeHudOperation.DREAMS:
                value = await self.client.dreams()
            elif operation is LifeHudOperation.LIFE:
                value = await self.client.life()
            elif operation is LifeHudOperation.JOURNAL:
                value = await self.client.journal(JournalInput.model_validate(payload).limit)
            elif operation is LifeHudOperation.MEDIA:
                value = await self.client.media()
            elif operation is LifeHudOperation.GROWTH:
                value = await self.client.growth()
            elif operation is LifeHudOperation.FOCUS_START:
                parsed = FocusStartInput.model_validate(payload)
                value = await self.client.start_iron_curtain(parsed.title, parsed.related_task_ids)
            else:
                parsed = FocusCompleteInput.model_validate(payload)
                value = await self.client.complete(parsed.session_id, parsed.note)
        except ValidationError as exc:
            return ToolResult(success=False, content="Life HUD 操作参数无效。", error=str(exc))
        except LifeHudError as exc:
            return self._error(exc)
        content = "已从 Life HUD 读取事实。"
        if operation is LifeHudOperation.FOCUS_START:
            content = "铁幕已开幕。"
        elif operation is LifeHudOperation.FOCUS_COMPLETE:
            content = "铁幕已落幕。"
        return self._success(value, operation, content=content)
