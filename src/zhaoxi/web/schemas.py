"""Validated request/response contracts shared by Web API routers."""
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict, StrictBool, model_validator
from zhaoxi.core.attachments import ImageList
from zhaoxi.interfaces.models import DisplayPart
from zhaoxi.expression import EmojiMetadata

class ChatRequest(BaseModel):
    message: str = Field(default="", max_length=20_000)
    display_parts: list[DisplayPart] = Field(default_factory=list, max_length=1000)
    images: ImageList = Field(default_factory=list)
    request_id: str | None = Field(default=None, min_length=1, max_length=128)


class ThinkingRequest(BaseModel):
    mode: Literal["off", "disabled", "enabled"]


class RegenerateRequest(BaseModel):
    message_id: str = Field(min_length=1, max_length=128)
    request_id: str | None = Field(default=None, min_length=1, max_length=128)


class ReplyRenderedRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=128)
    message_id: str = Field(min_length=1, max_length=128)
    first_render_ms: float | None = Field(default=None, ge=0, le=300_000)
    fully_rendered_ms: float | None = Field(default=None, ge=0, le=300_000)


class ToolControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["tool", "group", "all"]
    target: str | None = None
    enabled: StrictBool | None = None
    force_expose: StrictBool | None = None
    confirm_write: StrictBool | None = None
    reset: bool = False

    @model_validator(mode="after")
    def validate_target(self):
        if self.scope != "all" and not self.target:
            raise ValueError("必须指定钥匙或组")
        if self.scope == "all" and self.target:
            raise ValueError("全部操作不接受 target")
        if self.reset and (self.enabled is not None or self.force_expose is not None or self.confirm_write is not None):
            raise ValueError("恢复默认不能同时指定开关")
        if not self.reset and self.enabled is None and self.force_expose is None and self.confirm_write is None:
            raise ValueError("没有指定修改")
        return self


class ToolCapabilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str = Field(min_length=1)
    capability: str = Field(min_length=1)
    enabled: StrictBool


class InterfaceSettingsRequest(BaseModel):
    input_merge_seconds: int = Field(default=15, ge=0, le=30)
    reply_interval_seconds: int = Field(default=5, ge=0, le=15)
    external_input_debounce_seconds: float = Field(default=5, ge=0, le=15)
    external_reply_interval_seconds: float = Field(default=0.5, ge=0, le=5)
    long_wait_enabled: StrictBool = False
    force_fast_chat: StrictBool = False
    show_normal_regenerate: StrictBool = False


class FilesystemAccessRequest(BaseModel):
    read_directories: list[str] = Field(min_length=1, max_length=20)
    write_directories: list[str] = Field(min_length=1, max_length=20)


class EmojiControlRequest(BaseModel):
    enabled: StrictBool | None = None
    reload: bool = False
    intent: str | None = Field(default=None, max_length=500)
    emotion: str | None = Field(default=None, max_length=80)
    intensity: float | None = Field(default=None, ge=0, le=1)


class EmojiTraceAckRequest(BaseModel):
    trace_id: str = Field(min_length=1, max_length=128)
    received: bool = True
    rendered: bool = True


class RecentContextControlRequest(BaseModel):
    agenda_enabled: StrictBool | None = None


class InternalActivityDebugRequest(BaseModel):
    activity: Literal["tick", "current_cognition_consolidation", "memory_maintenance",
                      "agenda_maintenance", "proactive_check", "perception_cognition", "fast_digest",
                      "cognition_gardening", "memory_gardening", "cluster_gardening",
                      "memory_reminiscence", "social_lurk", "social_wander"] = "tick"
    confirm_social_write: StrictBool = False


class DecisionDebugRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    forced_level: Literal["L0", "L1", "L2"] | None = None


class PresenceDebugRequest(BaseModel):
    state: Literal["ACTIVE", "SEMI_ACTIVE", "IDLE", "AWAY", "SLEEP"] | None = Field(...)


class EmojiMetadataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=2, max_length=2000)
    tags: list[str] = Field(min_length=1, max_length=50)
    emotion: str | None = Field(default=None, max_length=80)
    intensity: float | None = Field(default=None, ge=0, le=1)
    enabled: bool = True

    def metadata(self) -> EmojiMetadata:
        return EmojiMetadata.model_validate(self.model_dump())


class EmojiCreateRequest(EmojiMetadataRequest):
    data_url: str = Field(min_length=32)


class EmojiPendingRequest(BaseModel):
    data_url: str = Field(min_length=32)


class EmojiAnalyzeRequest(BaseModel):
    data_url: str = Field(min_length=32)
    hint: str = Field(default="", max_length=1000)


class ChatResponse(BaseModel):
    timestamp: datetime | None = None
    content: str
    activity: dict[str, Any] = Field(default_factory=dict)
    permission: dict[str, Any] | None = None
    request_id: str | None = None
    trace_id: str | None = None
    status: str = "completed"
    message_id: str | None = None
    output_messages: list[dict[str, Any]] = Field(default_factory=list)


class VoiceConfirmRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    request_id: str | None = Field(default=None, min_length=1, max_length=128)


class VoiceSpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


