"""Current cognition journal data."""
from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field

class EvidenceRef(BaseModel):
    message_id: str = ""
    event_id: str = ""
    timestamp: datetime | None = None
    source: str = "owner"

class CognitionThread(BaseModel):
    key: str
    title: str = Field(max_length=40)
    summary: str = Field(max_length=160)
    status: Literal["active", "cooling", "resolved"] = "active"
    salience: float = Field(default=0.6, ge=0, le=1)
    first_seen_at: datetime
    last_updated_at: datetime
    last_evidence_at: datetime
    source_refs: list[EvidenceRef] = Field(default_factory=list, max_length=8)

class JournalItem(BaseModel):
    key: str
    text: str = Field(max_length=80)
    created_at: datetime
    updated_at: datetime
    source_refs: list[EvidenceRef] = Field(default_factory=list, max_length=4)

class CurrentCognitionState(BaseModel):
    version: int = 2
    overview: str = Field(default="", max_length=160)
    threads: list[CognitionThread] = Field(default_factory=list)
    recent_changes: list[JournalItem] = Field(default_factory=list)
    watch_items: list[JournalItem] = Field(default_factory=list)
    updated_at: datetime | None = None
    last_processed_message_id: str | None = None
    last_maintenance: dict = Field(default_factory=lambda: {"decision": "NEVER", "reason": ""})
    recent_decisions: list[dict] = Field(default_factory=list, max_length=10)
