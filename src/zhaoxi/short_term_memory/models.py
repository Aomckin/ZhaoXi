"""Bounded rolling state; items are internal evidence units, not user notes."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field


class Category(StrEnum):
    ACTIVE_CONTEXT = "active_context"
    ACTIVE_THREAD = "active_thread"
    RECENT_TOPIC = "recent_topic"
    RECENT_CHANGE = "recent_change"
    UNRESOLVED = "unresolved"


class Source(StrEnum):
    USER = "user"
    TOOL = "tool"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class Status(StrEnum):
    ACTIVE = "active"
    FADING = "fading"


LIMITS = {
    Category.ACTIVE_CONTEXT: 8,
    Category.ACTIVE_THREAD: 8,
    Category.RECENT_TOPIC: 6,
    Category.RECENT_CHANGE: 6,
    Category.UNRESOLVED: 8,
}


class ShortTermMemoryItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    category: Category
    content: str = Field(min_length=1, max_length=240)
    source: Source
    source_message_ids: list[str] = Field(default_factory=list, max_length=8)
    first_seen_at: datetime
    last_seen_at: datetime
    last_reinforced_at: datetime
    reinforcements: int = Field(default=1, ge=1)
    confidence: float = Field(default=1.0, ge=0, le=1)
    status: Status = Status.ACTIVE


class ShortTermMemoryState(BaseModel):
    version: int = Field(default=1, ge=1)
    overview: str = Field(default="", max_length=650)
    items: list[ShortTermMemoryItem] = Field(default_factory=list, max_length=36)
    updated_at: datetime | None = None
    last_processed_message_id: str | None = None
    last_maintenance: dict = Field(default_factory=lambda: {"result": "NEVER", "patch": None})
