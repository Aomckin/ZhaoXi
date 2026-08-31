"""Life HUD Focus tools used by workflows and the normal agent."""

from zhaoxi.permission.models import PermissionLevel, SideEffect
from zhaoxi.tools.base import Tool, ToolResult
from zhaoxi.tools.integrations.lifehud.client import LifeHudClient
from zhaoxi.tools.integrations.lifehud.errors import LifeHudError
from zhaoxi.tools.integrations.lifehud.models import (
    FocusCompleteInput,
    FocusCurrentInput,
    FocusStartInput,
)


class LifeHudTool(Tool):
    def __init__(self, client: LifeHudClient) -> None:
        self.client = client

    def _error(self, exc: LifeHudError) -> ToolResult:
        return ToolResult(
            success=False,
            content=str(exc),
            error=exc.code,
            metadata={"retryable": exc.retryable},
        )


class LifeHudFocusCurrentTool(LifeHudTool):
    name = "lifehud_focus_current"
    description = "查询 Life HUD 当前正在运行或暂停的 Focus。"
    input_model = FocusCurrentInput

    async def execute(self, arguments):
        try:
            value = await self.client.current()
        except LifeHudError as exc:
            return self._error(exc)
        if value is None:
            return ToolResult(success=True, content="当前没有 Focus。", data={"current": None})
        return ToolResult(
            success=True,
            content="已读取当前 Focus。",
            data={"current": self.client.dump_for_display(value)},
            metadata={"display_timezone": self.client.display_timezone},
        )


class LifeHudFocusStartTool(LifeHudTool):
    name = "lifehud_focus_start"
    description = "在 Life HUD 中开启铁幕 Focus。"
    input_model = FocusStartInput
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.LOCAL_STATE})

    def resource_scope(self, arguments):
        return "lifehud.focus:new:iron_curtain"

    async def execute(self, arguments):
        try:
            value = await self.client.start_iron_curtain(arguments.title, arguments.related_task_ids)
        except LifeHudError as exc:
            return self._error(exc)
        return ToolResult(
            success=True,
            content="铁幕已开幕。",
            data=self.client.dump_for_display(value),
            metadata={"display_timezone": self.client.display_timezone},
        )


class LifeHudFocusCompleteTool(LifeHudTool):
    name = "lifehud_focus_complete"
    description = "在 Life HUD 中结束指定铁幕 Focus。"
    input_model = FocusCompleteInput
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.LOCAL_STATE})

    def resource_scope(self, arguments):
        return f"lifehud.focus:{arguments.get('session_id', 'unknown')}"

    async def execute(self, arguments):
        try:
            value = await self.client.complete(arguments.session_id, arguments.note)
        except LifeHudError as exc:
            return self._error(exc)
        return ToolResult(
            success=True,
            content="铁幕已落幕。",
            data=self.client.dump_for_display(value),
            metadata={"display_timezone": self.client.display_timezone},
        )


def create_lifehud_focus_tools(client: LifeHudClient):
    return [
        LifeHudFocusCurrentTool(client),
        LifeHudFocusStartTool(client),
        LifeHudFocusCompleteTool(client),
    ]
