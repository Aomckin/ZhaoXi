"""Working-notes domain models and trust boundaries."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class NoteType(StrEnum):
    WORKING = "working"
    TODO = "todo"
    QUESTION = "question"
    DECISION = "decision"
    HYPOTHESIS = "hypothesis"
    TEMP = "temp"


class NoteSource(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class NoteConfidence(StrEnum):
    CONFIRMED = "confirmed"
    WORKING = "working"
    TENTATIVE = "tentative"


class NoteStatus(StrEnum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    EXPIRED = "expired"


class WorkingNote(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    topic: str = Field(min_length=1, max_length=200)
    type: NoteType
    content: str = Field(min_length=1, max_length=4000)
    source: NoteSource
    confidence: NoteConfidence
    status: NoteStatus = NoteStatus.ACTIVE
    related_project: str | None = Field(default=None, max_length=200)
    related_task: str | None = Field(default=None, max_length=200)
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def protect_provenance(self) -> "WorkingNote":
        if self.type is NoteType.HYPOTHESIS and self.confidence is not NoteConfidence.TENTATIVE:
            raise ValueError("hypothesis 必须是 tentative")
        if self.source is NoteSource.ASSISTANT and self.confidence is NoteConfidence.CONFIRMED:
            raise ValueError("assistant 便签不能标记为 confirmed")
        return self
