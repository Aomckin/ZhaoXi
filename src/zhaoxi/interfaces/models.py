"""Transport-neutral input and output models for Zhaoxi interfaces."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator
from zhaoxi.core.attachments import ImageList


class InterfaceChannel(StrEnum):
    CLI = "cli"
    WEB = "web"
    DESKTOP = "desktop"
    VOICE = "voice"


class MessageOrigin(StrEnum):
    USER = "user"
    PROACTIVE = "proactive"
    SYSTEM = "system"


class DisplayPart(BaseModel):
    text: str = Field(default="", max_length=20_000)
    image_count: int = Field(default=0, ge=0, le=20)
    timestamp: datetime


class UnifiedMessage(BaseModel):
    """A bounded message entering Core through a known local interface."""

    message_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=128)
    request_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=128)
    session_id: str = Field(default="local", min_length=1, max_length=128)
    channel: InterfaceChannel
    origin: MessageOrigin = MessageOrigin.USER
    content: str = Field(min_length=1, max_length=20_000)
    images: ImageList = Field(default_factory=list)
    display_parts: list[DisplayPart] = Field(default_factory=list, max_length=1000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reply_to: str | None = Field(default=None, max_length=128)
    capabilities: set[str] = Field(default_factory=set, max_length=20)
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("消息内容不能为空")
        return normalized

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, value: set[str]) -> set[str]:
        if any(not item or len(item) > 64 for item in value):
            raise ValueError("capability 必须是 1 到 64 字符的名称")
        return value

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 20:
            raise ValueError("metadata 字段不能超过 20 个")
        if any(not key or len(key) > 64 for key in value):
            raise ValueError("metadata key 必须是 1 到 64 字符的名称")
        if sum(len(str(key)) + len(str(item)) for key, item in value.items()) > 2_000:
            raise ValueError("metadata 过大")
        return value


class PermissionView(BaseModel):
    confirmation_id: str
    action: str
    permission: str
    resource_scope: str | None = None
    risk: str


class UnifiedResponse(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    request_id: str
    session_id: str = "local"
    trace_id: str | None = None
    status: str = "completed"
    content: str = ""
    activity: dict[str, Any] = Field(default_factory=dict)
    permission: PermissionView | None = None

    @field_validator("content")
    @classmethod
    def clean_internal_timeline_header(cls, value: str) -> str:
        # Final defense at every interface boundary, including planner/workflow paths.
        from zhaoxi.core.message import strip_echoed_timeline_header

        return strip_echoed_timeline_header(value)
