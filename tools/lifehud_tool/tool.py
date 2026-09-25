"""The single operation-based Tool exposed by LifeHUD-Tool."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from zhaoxi.sdk import PermissionLevel, SideEffect, Tool, ToolResult

from tools.lifehud_tool.client import LifeHudClient
from tools.lifehud_tool.errors import LifeHudError
from tools.lifehud_tool.living_io import LivingIO
from tools.lifehud_tool.models import FocusCompleteInput, FocusStartInput, JournalInput, RecentInput


class LifeHudOperation(StrEnum):
    CONTEXT = "context"
    RECORD = "record"
    JOURNAL_IO = "journal"
    FOCUS = "focus"
    TASK = "task"
    RITUAL = "ritual"
    MEDIA_IO = "media"
    DREAM = "dream"
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
    model_config = ConfigDict(extra="allow")
    operation: LifeHudOperation
    arguments: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def accept_flat_business_arguments(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        extra = {key: item for key, item in value.items() if key not in {"operation", "arguments"}}
        if not extra:
            return value
        nested = value.get("arguments", {})
        if not isinstance(nested, dict):
            return value
        return {"operation": value.get("operation"), "arguments": {**extra, **nested}}


class LifeHudTool(Tool):
    name = "lifehud"
    aliases = ("Life HUD", "生活面板", "生活记录")
    intents = (
        "查看今天吃了什么",
        "评价今天饮食",
        "查询饮食记录",
        "查看今天做过什么",
        "查询睡眠记录",
        "查询任务完成情况",
        "查询 FocusSession",
        "查询铁幕记录",
        "查看能量",
        "查看经验",
        "查看近期生活状态",
        "记录睡眠饮食运动",
        "记录喝水咖啡和户外活动",
        "保存带图片的生活记录或日记",
        "记录番剧游戏进度",
        "完成 Life HUD 任务或仪式",
    )
    description = (
        "读取和记录 Life HUD 生活事实。operation=context|record|journal|focus|task|ritual|media|dream，"
        "具体动作放在 arguments.action，record 使用 arguments.type。可记录睡眠、饮食、运动、状态、饮水、咖啡因、"
        "日记及图片，也可管理专注、任务、媒体进度、仪式和梦想。图片使用 images=['<current-message-image>']，"
        "多图可用 <current-message-image:2> 等序号。只在用户有记录/查询意图或既定主动记录策略时使用；"
        "普通闲聊提到活动不应自动落库。兼容旧版 context.* 与 focus.start/complete。"
    )
    input_model = LifeHudInput

    def __init__(self, client: LifeHudClient, enabled: dict[str, bool] | None = None) -> None:
        self.client = client
        self._default_capabilities = {name: (enabled or {}).get(name, True) for name in
                                      ("context", "write", "image", "focus", "media", "dream", "ritual")}
        self.living = LivingIO(client, dict(self._default_capabilities)) if client is not None else None

    def capability_flags(self) -> dict[str, bool]:
        return dict(self.living.enabled) if self.living is not None else dict(self._default_capabilities)

    def set_capability(self, name: str, enabled: bool) -> None:
        if name not in self._default_capabilities or type(enabled) is not bool:
            raise ValueError("不支持的 LifeHUD 能力组或开关值。")
        self.living.enabled[name] = enabled

    def reset_capabilities(self) -> None:
        self.living.enabled = dict(self._default_capabilities)

    @staticmethod
    def _operation(arguments: dict[str, Any]) -> LifeHudOperation:
        return LifeHudOperation(arguments["operation"])

    def permission_for(self, arguments: dict[str, Any]) -> PermissionLevel:
        operation = self._operation(arguments)
        payload = arguments.get("arguments", {})
        if operation in {LifeHudOperation.RECORD, LifeHudOperation.JOURNAL_IO,
                         LifeHudOperation.FOCUS, LifeHudOperation.TASK,
                         LifeHudOperation.RITUAL, LifeHudOperation.MEDIA_IO,
                         LifeHudOperation.DREAM}:
            action = payload.get("action", "create" if operation is LifeHudOperation.RECORD else "list")
            if action in {"delete", "purge", "remove"}:
                return PermissionLevel.DELETE
            if action in {"list", "get", "read", "current", "today", "history", "get_execution"}:
                return PermissionLevel.READ
            return PermissionLevel.WRITE
        if operation in {LifeHudOperation.FOCUS_START, LifeHudOperation.FOCUS_COMPLETE}:
            return PermissionLevel.WRITE
        return PermissionLevel.READ

    def side_effects_for(self, arguments: dict[str, Any]) -> frozenset[SideEffect]:
        if self.permission_for(arguments) is PermissionLevel.WRITE:
            return frozenset({SideEffect.EXTERNAL_SERVICE_WRITE})
        if self.permission_for(arguments) is PermissionLevel.DELETE:
            return frozenset({SideEffect.DATA_DELETION})
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
        if operation in {LifeHudOperation.RECORD, LifeHudOperation.JOURNAL_IO,
                         LifeHudOperation.FOCUS, LifeHudOperation.TASK,
                         LifeHudOperation.RITUAL, LifeHudOperation.MEDIA_IO,
                         LifeHudOperation.DREAM}:
            return f"lifehud.{operation.value}:{payload.get('type', '')}:{payload.get('id', 'new')}"
        return f"lifehud:{operation.value}"

    def confirmation_description(self, arguments: dict[str, Any]) -> str:
        operation = self._operation(arguments)
        if operation is LifeHudOperation.FOCUS_START:
            return "在 Life HUD 中开启铁幕 Focus"
        if operation is LifeHudOperation.FOCUS_COMPLETE:
            return "在 Life HUD 中结束铁幕 Focus"
        return self.description.split("。", 1)[0]

    def _error(self, exc: LifeHudError, operation: LifeHudOperation | None = None,
               payload: dict[str, Any] | None = None) -> ToolResult:
        warning = ["image_uploaded_but_record_failed"] if getattr(exc, "image_uploaded_but_record_failed", False) else []
        write = operation is not None and self.permission_for({"operation": operation.value,
                                                               "arguments": payload or {}}) is PermissionLevel.WRITE
        unknown_outcome = write and exc.code in {"lifehud_unavailable", "lifehud_server_error", "confirmation_failed"}
        return ToolResult(
            success=False,
            content=str(exc),
            error=exc.code,
            data={"ok": False, "error": {"type": exc.code, "message": str(exc)}, "warnings": warning},
            metadata={
                "retryable": exc.retryable,
                "safe_to_replay": False,
                "unknown_outcome": unknown_outcome,
                "fact_source": "lifehud",
            },
        )

    def _success(self, value, operation: LifeHudOperation, *, content: str) -> ToolResult:
        serialized = self.client.dump_for_display(value)
        if operation in {LifeHudOperation.CONTEXT, LifeHudOperation.RECORD, LifeHudOperation.JOURNAL_IO,
                         LifeHudOperation.FOCUS, LifeHudOperation.TASK, LifeHudOperation.RITUAL,
                         LifeHudOperation.MEDIA_IO, LifeHudOperation.DREAM}:
            serialized = {"ok": True, "operation": operation.value,
                          "action": value.get("action") if isinstance(value, dict) else "read",
                          "resource": value.get("resource") if isinstance(value, dict) else operation.value,
                          "data": serialized, "warnings": value.get("warnings", []) if isinstance(value, dict) else []}
        return ToolResult(
            success=True,
            content=content,
            data=serialized,
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
            if operation.value.startswith("context."):
                self.living._require_enabled("context")
            elif operation.value.startswith("focus."):
                self.living._require_enabled("focus")
                if operation in {LifeHudOperation.FOCUS_START, LifeHudOperation.FOCUS_COMPLETE}:
                    self.living._require_enabled("write")
            if operation is LifeHudOperation.CONTEXT:
                value = await self.living.context(payload)
            elif operation is LifeHudOperation.RECORD:
                value = await self.living.record(payload)
            elif operation is LifeHudOperation.JOURNAL_IO:
                value = await self.living.journal(payload)
            elif operation is LifeHudOperation.FOCUS:
                value = await self.living.focus(payload)
            elif operation is LifeHudOperation.TASK:
                value = await self.living.task(payload)
            elif operation in {LifeHudOperation.RITUAL, LifeHudOperation.MEDIA_IO, LifeHudOperation.DREAM}:
                value = await self.living.generic(operation.value, payload)
            elif operation is LifeHudOperation.TODAY:
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
        except ValidationError:
            return ToolResult(success=False, content="Life HUD 操作参数无效。", error="validation_error",
                              data={"ok": False, "error": {"type": "validation_error", "message": "Life HUD 操作参数无效。"}})
        except LifeHudError as exc:
            return self._error(exc, operation, payload)
        content = "已从 Life HUD 读取事实。"
        if operation is LifeHudOperation.FOCUS_START:
            content = "铁幕已开幕。"
        elif operation is LifeHudOperation.FOCUS_COMPLETE:
            content = "铁幕已落幕。"
        return self._success(value, operation, content=content)
