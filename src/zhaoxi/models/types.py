"""Provider-neutral model response types."""

from typing import Any

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    """A provider-neutral request to invoke one tool."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ModelResponse(BaseModel):
    """Normalized output returned by every model provider."""

    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)

