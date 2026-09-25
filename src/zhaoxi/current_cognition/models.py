"""Narrative-first current cognition, distinct from long-term fact storage."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TopicObservation(BaseModel):
    key: str = Field(min_length=2, max_length=60)
    message_ids: list[str] = Field(default_factory=list, max_length=8)
    count: int = Field(default=0, ge=0)
    last_seen_at: datetime


class CurrentCognitionState(BaseModel):
    version: int = Field(default=1, ge=1)
    narrative: str = Field(default="", max_length=700)
    ongoing_threads: list[str] = Field(default_factory=list, max_length=4)
    attention: list[str] = Field(default_factory=list, max_length=3)
    observations: list[TopicObservation] = Field(default_factory=list, max_length=12)
    updated_at: datetime | None = None
    last_processed_message_id: str | None = None
    last_maintenance: dict = Field(default_factory=lambda: {"decision": "NEVER", "reason": ""})
    recent_decisions: list[dict] = Field(default_factory=list, max_length=10)
