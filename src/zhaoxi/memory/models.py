"""Provider-independent long-term memory models."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryKind(StrEnum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"


class MemorySourceType(StrEnum):
    USER = "user"
    CONVERSATION = "conversation"
    TOOL = "tool"
    SYSTEM = "system"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    FORGOTTEN = "forgotten"


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    kind: MemoryKind = MemoryKind.SEMANTIC
    summary: str | None = Field(default=None, max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=30)
    source_type: MemorySourceType = MemorySourceType.USER
    source_ref: str | None = Field(default=None, max_length=500)
    confidence: float = Field(default=1.0, ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    supersedes_id: str | None = None

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("memory content cannot be blank")
        return value

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            normalized = value.strip().lower()
            if normalized and normalized not in result:
                result.append(normalized)
        return result


class MemoryUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=20_000)
    kind: MemoryKind | None = None
    summary: str | None = Field(default=None, max_length=500)
    tags: list[str] | None = Field(default=None, max_length=30)
    confidence: float | None = Field(default=None, ge=0, le=1)
    metadata: dict[str, Any] | None = None

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        if not value:
            raise ValueError("memory content cannot be blank")
        return value

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        result: list[str] = []
        for value in values:
            normalized = value.strip().lower()
            if normalized and normalized not in result:
                result.append(normalized)
        return result


class MemoryQuery(BaseModel):
    text: str = ""
    kind: MemoryKind | None = None
    tags: list[str] = Field(default_factory=list)
    source_type: MemorySourceType | None = None
    statuses: list[MemoryStatus] = Field(default_factory=lambda: [MemoryStatus.ACTIVE])
    limit: int = Field(default=10, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class MemoryRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    kind: MemoryKind
    content: str
    normalized_content: str
    summary: str | None = None
    tags: list[str] = Field(default_factory=list)
    source_type: MemorySourceType
    source_ref: str | None = None
    confidence: float
    status: MemoryStatus = MemoryStatus.ACTIVE
    supersedes_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    accessed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemorySearchResult(BaseModel):
    record: MemoryRecord
    score: float = 0
    match_reason: str = ""


class MemoryWriteResult(BaseModel):
    record: MemoryRecord
    created: bool
    duplicate: bool = False
    conflict_candidates: list[MemoryRecord] = Field(default_factory=list)
