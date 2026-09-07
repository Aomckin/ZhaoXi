"""Internal conversation message model."""

from datetime import datetime, timezone
from enum import StrEnum
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

from zhaoxi.models.types import ToolCall
from zhaoxi.core.attachments import ImageList


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


_TIMELINE_HEADER = re.compile(
    r"^\s*\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?"
    r"(?:Z|[+-]\d{2}:\d{2})\s*·\s*(?:assistant|user|朝汐主动消息)\]\s*\r?\n"
)


def strip_echoed_timeline_header(content: str) -> str:
    """Remove only a leaked internal timeline header at the start of a reply."""
    return _TIMELINE_HEADER.sub("", content, count=1)


class Message(BaseModel):
    """Provider-independent message used throughout the core."""

    role: Role
    content: str | None = None
    images: ImageList = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    delivery_id: str | None = None
    background: str = Field(default="", max_length=2000)

    @field_validator("timestamp")
    @classmethod
    def aware_timestamp(cls, value: datetime) -> datetime:
        # Older explicit naive timestamps used UTC throughout the application.
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

    def to_provider_dict(self) -> dict[str, Any]:
        """Convert only at the provider boundary."""
        result: dict[str, Any] = {"role": self.role.value, "content": self.content}
        if self.images:
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


def json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

