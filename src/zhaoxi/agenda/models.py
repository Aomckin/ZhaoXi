"""Agenda domain models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class AgendaType(StrEnum):
    EVENT = "event"
    WINDOW = "window"
    DEADLINE = "deadline"
    FOCUS = "focus"
    EXPECTATION = "expectation"


class AgendaStatus(StrEnum):
    PLANNED = "planned"
    ACTIVE = "active"
    DONE = "done"
    MISSED = "missed"
    CANCELLED = "cancelled"
    RESCHEDULED = "rescheduled"


class AgendaItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    type: AgendaType
    title: str = Field(min_length=1, max_length=500)
    start_at: datetime | None = None
    end_at: datetime | None = None
    due_at: datetime | None = None
    status: AgendaStatus = AgendaStatus.PLANNED
    priority: int = Field(default=0, ge=0, le=3)
    note: str = Field(default="", max_length=2000)
    source: str = Field(default="user", max_length=40)
    scope: str | None = Field(default=None, max_length=80)
    condition: str | None = Field(default=None, max_length=500)
    secondary: bool = False
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_times(self) -> "AgendaItem":
        if self.type in {AgendaType.EVENT, AgendaType.WINDOW} and self.start_at is None:
            raise ValueError("event/window 必须提供 start_at")
        if self.type is AgendaType.DEADLINE and self.due_at is None:
            raise ValueError("deadline 必须提供 due_at")
        if self.end_at and self.start_at and self.end_at < self.start_at:
            raise ValueError("end_at 不能早于 start_at")
        return self
