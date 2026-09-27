"""External observations retain source provenance and never become user turns."""
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4
from pydantic import BaseModel, Field, field_validator


class TrustLevel(StrEnum):
    TRUSTED = "TRUSTED"
    NORMAL = "NORMAL"
    LOW = "LOW"
    UNVERIFIED = "UNVERIFIED"


class AttentionHint(StrEnum):
    IGNORE = "IGNORE"
    AMBIENT = "AMBIENT"
    DIRECT = "DIRECT"
    URGENT = "URGENT"


class ObservationStatus(StrEnum):
    PENDING = "PENDING"
    BUFFERED = "BUFFERED"
    PROCESSED = "PROCESSED"
    IGNORED = "IGNORED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class ObservationPart(BaseModel):
    type: str
    text: str | None = None
    url: str | None = None
    file: str | None = None
    target: str | None = None


class Observation(BaseModel):
    observation_id: str = Field(default_factory=lambda: uuid4().hex)
    source: str
    source_kind: str
    actor_id: str | None = None
    actor_name: str | None = None
    actor_role: str = "EXTERNAL"
    conversation_id: str | None = None
    conversation_kind: str | None = None
    content: str = ""
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    parts: list[ObservationPart] = Field(default_factory=list)

    @property
    def effective_parts(self) -> list[ObservationPart]:
        if self.parts:
            return self.parts
        result = [ObservationPart(type="text", text=self.content)] if self.content else []
        result += [ObservationPart(type="image", url=item.get("url"), file=item.get("file"))
                   for item in self.attachments if item.get("type") == "image"]
        return result
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    received_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    trust_level: TrustLevel = TrustLevel.UNVERIFIED
    attention_hint: AttentionHint = AttentionHint.AMBIENT
    directed_to_zhaoxi: bool = False
    directed_to_user: bool = False
    requeryable: bool = False
    raw_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("occurred_at", "received_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observation timestamp requires timezone")
        return value.astimezone(UTC)


class ObservationBatch(BaseModel):
    batch_id: str = Field(default_factory=lambda: uuid4().hex)
    source: str
    conversation_id: str
    window_start: datetime
    window_end: datetime
    observation_ids: list[str]
    raw_refs: list[str]


class SocialSnapshot(BaseModel):
    snapshot_id: str = Field(default_factory=lambda: uuid4().hex)
    batch_id: str
    source: str
    conversation_id: str
    window_start: datetime
    window_end: datetime
    message_count: int
    participants: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    summary: str
    mentions_of_user: list[str] = Field(default_factory=list)
    mentions_of_zhaoxi: list[str] = Field(default_factory=list)
    possible_tasks: list[str] = Field(default_factory=list)
    possible_facts: list[str] = Field(default_factory=list)
    observation_ids: list[str]
    raw_refs: list[str]
    confidence: float = Field(ge=0, le=1)
