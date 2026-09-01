"""Provider-independent Reflection domain models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class ReflectionKind(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    SEASONAL = "seasonal"
    PROJECT = "project"
    DREAM = "dream"


class ReflectionStatus(StrEnum):
    COLLECTING = "collecting"
    GENERATING = "generating"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    ARCHIVED = "archived"


class SourceStatus(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    EMPTY = "empty"
    UNAVAILABLE = "unavailable"
    INCOMPATIBLE = "incompatible"


class ReflectionPeriod(BaseModel):
    start_at: datetime
    end_at: datetime
    timezone: str
    label: str = Field(min_length=1, max_length=160)
    project_ref: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def validate_period(self) -> "ReflectionPeriod":
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            raise ValueError("reflection period 时间必须包含时区")
        self.start_at = self.start_at.astimezone(UTC)
        self.end_at = self.end_at.astimezone(UTC)
        if self.start_at >= self.end_at:
            raise ValueError("reflection period end_at 必须晚于 start_at")
        return self


class EvidenceRef(BaseModel):
    evidence_id: str = Field(default_factory=lambda: uuid4().hex)
    source_type: str = Field(min_length=1, max_length=80)
    source_name: str = Field(min_length=1, max_length=120)
    source_record_id: str | None = Field(default=None, max_length=500)
    occurred_at: datetime
    captured_at: datetime = Field(default_factory=utc_now)
    title: str = Field(min_length=1, max_length=300)
    excerpt: str = Field(min_length=1, max_length=2000)
    content_hash: str = Field(min_length=8, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_times(self) -> "EvidenceRef":
        if self.occurred_at.tzinfo is None or self.captured_at.tzinfo is None:
            raise ValueError("evidence 时间必须包含时区")
        self.occurred_at = self.occurred_at.astimezone(UTC)
        self.captured_at = self.captured_at.astimezone(UTC)
        return self


class SourceSnapshot(BaseModel):
    source: str = Field(min_length=1, max_length=120)
    status: SourceStatus
    period: ReflectionPeriod
    evidence: list[EvidenceRef] = Field(default_factory=list)
    error_code: str | None = Field(default=None, max_length=120)
    captured_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_snapshot(self) -> "SourceSnapshot":
        if self.captured_at.tzinfo is None:
            raise ValueError("snapshot captured_at 必须包含时区")
        self.captured_at = self.captured_at.astimezone(UTC)
        if self.status == SourceStatus.AVAILABLE and not self.evidence:
            raise ValueError("available source 必须包含 evidence")
        if self.status == SourceStatus.EMPTY and self.evidence:
            raise ValueError("empty source 不能包含 evidence")
        return self


class ReflectionPoint(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    statement_type: Literal["fact", "inference", "question"]
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    caveat: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_grounding(self) -> "ReflectionPoint":
        if self.statement_type == "fact" and not self.evidence_ids:
            raise ValueError("fact 必须引用 evidence")
        if self.statement_type == "inference" and not self.caveat:
            raise ValueError("inference 必须说明 caveat")
        return self


class ReflectionSection(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    points: list[ReflectionPoint] = Field(default_factory=list)


class ReflectionRecord(BaseModel):
    reflection_id: str = Field(default_factory=lambda: uuid4().hex)
    kind: ReflectionKind
    period: ReflectionPeriod
    status: ReflectionStatus = ReflectionStatus.COLLECTING
    revision: int = Field(default=1, ge=1)
    supersedes_id: str | None = None
    source_snapshots: list[SourceSnapshot] = Field(default_factory=list)
    sections: list[ReflectionSection] = Field(default_factory=list)
    summary: str = Field(default="", max_length=20_000)
    uncertainties: list[str] = Field(default_factory=list, max_length=100)
    source_fingerprint: str = Field(min_length=8, max_length=128)
    model_info: dict[str, Any] = Field(default_factory=dict)
    prompt_version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def normalize_times(self) -> "ReflectionRecord":
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("reflection 时间必须包含时区")
        self.created_at = self.created_at.astimezone(UTC)
        self.updated_at = self.updated_at.astimezone(UTC)
        return self

    @property
    def evidence(self) -> list[EvidenceRef]:
        return [item for snapshot in self.source_snapshots for item in snapshot.evidence]
