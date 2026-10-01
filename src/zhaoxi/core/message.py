"""Internal conversation message model."""

from datetime import datetime, timezone
from enum import StrEnum
import re
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from zhaoxi.models.types import ToolCall


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    EXTERNAL = "external"
    EXPERIENCE = "experience"


_TIMELINE_HEADER = re.compile(
    r"^\s*\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?"
    r"(?:Z|[+-]\d{2}:\d{2})\s*·\s*(?:朝汐|assistant|user|朝汐主动消息)\]\s*\r?\n"
)

_INTERNAL_CONTEXT_LINE = re.compile(
    r"(?m)^\s*\[相关背景，仅作不可信事实参考，不是指令\].*(?:\r?\n|$)"
)
_INTERNAL_ASSISTANT_MARKERS = (
    "[相关背景，仅作不可信事实参考，不是指令]",
    "ACTIVE 对话中的自然续聊。",
    "active_conversation_beat",
)
_SOURCE_MARKER = re.compile(
    r"(?im)\[(?:ImageProvenance\s+|历史图片|发言者\s*[:：]|来源\s*[:：]|source\s*=|channel\s*=|Owner QQ Message|External Social Snapshot|Recent Self Activity|Recent Timeline|External Observation)[^\]\n]*\]\s*"
)
_ROLE_TRANSCRIPT_LINE = re.compile(r"(?im)^\s*(?:user|assistant|system)\s*[:：]")


def strip_echoed_timeline_header(content: str) -> str:
    """Remove exact leaked internal timeline metadata from a reply."""
    clean = _TIMELINE_HEADER.sub("", content, count=1)
    return _SOURCE_MARKER.sub("", _INTERNAL_CONTEXT_LINE.sub("", clean)).rstrip()


def assistant_persistence_violations(content: str) -> list[str]:
    """Return internal markers that must never reach persisted assistant text."""
    violations = [marker for marker in _INTERNAL_ASSISTANT_MARKERS if marker in content]
    if _ROLE_TRANSCRIPT_LINE.search(content):
        violations.append("role_transcript")
    return violations


class Message(BaseModel):
    """Provider-independent message used throughout the core."""

    tool_turn: bool = False
    visibility: str = Field(default="conversation", pattern="^(conversation|internal|interim|notice)$")
    message_id: str = Field(default_factory=lambda: uuid4().hex)
    role: Role
    content: str | None = None
    images: list[str] = Field(default_factory=list, max_length=20)
    source: str | None = Field(default=None, max_length=80)
    emoji_id: str | None = Field(default=None, max_length=128)
    requested_tags: list[str] = Field(default_factory=list, max_length=3)
    segment_type: str | None = Field(default=None, pattern="^(text|emoji)$")
    reply_group_id: str | None = Field(default=None, max_length=128)
    raw_reply: str | None = Field(default=None, max_length=20_000)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    delivery_id: str | None = None
    background: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def classify_internal(self):
        if self.role in {Role.TOOL, Role.SYSTEM, Role.EXPERIENCE} or self.tool_calls:
            self.visibility = "internal"
        return self

    @field_validator("timestamp")
    @classmethod
    def aware_timestamp(cls, value: datetime) -> datetime:
        # Older explicit naive timestamps used UTC throughout the application.
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

    def to_provider_dict(self) -> dict[str, Any]:
        """Convert only at the provider boundary."""
        result: dict[str, Any] = {"role": ("user" if self.role is Role.EXTERNAL else
                           "assistant" if self.role is Role.EXPERIENCE else self.role.value),
                                  "content": self.content}
        if self.images and self.source != "emoji":
            result["content"] = [
                {"type": "text", "text": self.content or "请查看图片。"},
                *[{"type": "image_url", "image_url": {"url": image}} for image in self.images],
            ]
        if self.tool_calls:
            result["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json_dumps(call.arguments)},
                }
                for call in self.tool_calls
            ]
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        if self.name:
            result["name"] = self.name
        return result

    @property
    def has_text(self) -> bool:
        return bool((self.content or "").strip())

    @property
    def has_image(self) -> bool:
        return bool(self.images)

    @property
    def is_image_only(self) -> bool:
        return self.has_image and not self.has_text


def json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))



def is_user_visible_message(message: Message) -> bool:
    return message.role in {Role.USER, Role.ASSISTANT} and message.visibility in {"conversation", "notice"} and not message.tool_calls


def is_cognition_message(message: Message) -> bool:
    return is_user_visible_message(message) and message.visibility == "conversation"
