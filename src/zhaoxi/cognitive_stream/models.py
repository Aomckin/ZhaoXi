"""Channel independent events with explicit trust and provenance."""
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4
from pydantic import BaseModel, Field, field_validator

class CognitiveEventType(StrEnum):
    USER_MESSAGE = "USER_MESSAGE"
    EXTERNAL_MESSAGE = "EXTERNAL_MESSAGE"
    ASSISTANT_REPLY = "ASSISTANT_REPLY"
    SOCIAL_SNAPSHOT = "SOCIAL_SNAPSHOT"
    TOOL_OBSERVATION = "TOOL_OBSERVATION"
    TOOL_ACTION = "TOOL_ACTION"
    WORKFLOW_EVENT = "WORKFLOW_EVENT"
    PLANNER_EVENT = "PLANNER_EVENT"
    PROACTIVE_EVENT = "PROACTIVE_EVENT"
    SYSTEM_EVENT = "SYSTEM_EVENT"
    SELF_EVENT = "SELF_EVENT"

class EventPart(BaseModel):
    type: str
    text: str | None = None
    url: str | None = None
    file: str | None = None
    target: str | None = None

class CognitiveEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    turn_id: str | None = None
    reply_to_event_id: str | None = None
    caused_by_event_id: str | None = None
    event_type: CognitiveEventType
    source: str
    channel: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None
    actor_id: str | None = None
    actor_name: str | None = None
    actor_role: str | None = None
    content: str | None = None
    parts: list[EventPart] = Field(default_factory=list)
    trust_level: str = "UNVERIFIED"
    privacy_level: str = "PRIVATE"
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    received_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    parent_refs: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    importance: float = Field(default=0.5, ge=0, le=1)
    attention_score: float = Field(default=0.5, ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("occurred_at", "received_at")
    @classmethod
    def utc_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("event timestamp requires timezone")
        return value.astimezone(UTC)

class EpisodeSummary(BaseModel):
    level: str = "L2"
    source_event_ids: list[str] = Field(default_factory=list)
    episode_id: str = Field(default_factory=lambda: uuid4().hex)
    content: str
    parent_refs: list[str]
    source_refs: list[str]
    occurred_at: datetime
