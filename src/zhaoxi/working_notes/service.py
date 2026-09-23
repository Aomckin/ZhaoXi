"""Conservative working-note maintenance and compact formatting."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import Callable
from zoneinfo import ZoneInfo

from zhaoxi.working_notes.models import (
    NoteConfidence, NoteSource, NoteStatus, NoteType, WorkingNote,
)
from zhaoxi.working_notes.sqlite import SQLiteWorkingNotesStore

logger = logging.getLogger("WORKING_NOTES")


def _key(value: str) -> str:
    return re.sub(r"\s+|[，。！？,.!?]", "", value).casefold()


class WorkingNotesService:
    def __init__(self, store: SQLiteWorkingNotesStore, *, timezone: str = "Asia/Shanghai",
                 max_context_items: int = 10, max_active_per_type: int = 10,
                 clock: Callable[[], datetime] | None = None) -> None:
        self.store = store
        self.timezone = ZoneInfo(timezone)
        self.max_context_items = max_context_items
        self.max_active_per_type = max_active_per_type
        self.clock = clock

    def now(self) -> datetime:
        value = self.clock() if self.clock else datetime.now(self.timezone)
        return value.astimezone(self.timezone) if value.tzinfo else value.replace(tzinfo=self.timezone)

    def add(self, *, topic: str, type: NoteType, content: str, source: NoteSource,
            confidence: NoteConfidence, expires_at: datetime | None = None,
            related_project: str | None = None, related_task: str | None = None) -> tuple[WorkingNote, bool]:
        now = self.now()
        if source is NoteSource.ASSISTANT and type is NoteType.HYPOTHESIS:
            confidence = NoteConfidence.TENTATIVE
        if source is NoteSource.ASSISTANT and confidence is NoteConfidence.CONFIRMED:
            confidence = NoteConfidence.WORKING
        active = self.list("active", now=now)
        for old in active:
            same_topic = _key(old.topic) == _key(topic)
            similarity = SequenceMatcher(None, _key(old.content), _key(content)).ratio()
            if old.type is type and (same_topic or similarity >= 0.88):
                return self.update(old.id, topic=topic, content=content, source=source,
                                   confidence=confidence, expires_at=expires_at,
                                   related_project=related_project, related_task=related_task), False
        same_type = [note for note in active if note.type is type]
        if len(same_type) >= self.max_active_per_type:
            oldest = min(same_type, key=lambda note: note.updated_at)
            oldest.status = NoteStatus.EXPIRED
            oldest.updated_at = now
            self.store.save(oldest)
            logger.info("action=expired id=%s type=%s timestamp=%s capacity=true", oldest.id, oldest.type.value, now.isoformat())
        expiry = self._aware(expires_at) if expires_at else None
        note = WorkingNote(topic=topic.strip(), type=type, content=content.strip(), source=source,
                           confidence=confidence, expires_at=expiry, related_project=related_project,
                           related_task=related_task, created_at=now, updated_at=now)
        self.store.save(note)
        logger.info("action=created id=%s type=%s timestamp=%s", note.id, note.type.value, now.isoformat())
        return note, True

    def update(self, note_id: str, **changes) -> WorkingNote:
        note = self.require(note_id)
        now = self.now()
        if changes.get("expires_at"):
            changes["expires_at"] = self._aware(changes["expires_at"])
        source = changes.get("source", note.source)
        confidence = changes.get("confidence", note.confidence)
        note_type = changes.get("type", note.type)
        if source is NoteSource.ASSISTANT and note_type is NoteType.HYPOTHESIS:
            changes["confidence"] = NoteConfidence.TENTATIVE
        elif source is NoteSource.ASSISTANT and confidence is NoteConfidence.CONFIRMED:
            changes["confidence"] = NoteConfidence.WORKING
        note = note.model_copy(update={**changes, "updated_at": now})
        note = WorkingNote.model_validate(note.model_dump())
        self.store.save(note)
        logger.info("action=updated id=%s type=%s timestamp=%s", note.id, note.type.value, now.isoformat())
        return note

    def resolve(self, note_id: str) -> WorkingNote:
        note = self.require(note_id)
        note.status = NoteStatus.RESOLVED
        note.updated_at = self.now()
        self.store.save(note)
        logger.info("action=resolved id=%s type=%s timestamp=%s", note.id, note.type.value, note.updated_at.isoformat())
        return note

    def delete(self, note_id: str) -> None:
        if not self.store.delete(note_id):
            raise ValueError("Working Note 不存在。")
        logger.info("action=deleted id=%s timestamp=%s", note_id, self.now().isoformat())

    def require(self, note_id: str) -> WorkingNote:
        note = self.store.get(note_id)
        if note is None:
            raise ValueError("Working Note 不存在。")
        return note

    def list(self, filter: str = "active", *, now: datetime | None = None) -> list[WorkingNote]:
        notes = self._refresh(now or self.now())
        if filter == "all_recent":
            return notes[:50]
        if filter == "resolved":
            return [note for note in notes if note.status is NoteStatus.RESOLVED][:10]
        if filter == "expired":
            return [note for note in notes if note.status is NoteStatus.EXPIRED][:10]
        if filter != "active":
            raise ValueError("Working Notes filter 无效。")
        return [note for note in notes if note.status is NoteStatus.ACTIVE]

    def snapshot(self, *, now: datetime | None = None) -> str:
        notes = self.list("active", now=now)
        sections = (
            ("Working", lambda n: n.type is NoteType.WORKING),
            ("Next", lambda n: n.type is NoteType.TODO),
            ("Open Questions", lambda n: n.type is NoteType.QUESTION),
            ("Confirmed", lambda n: n.confidence is NoteConfidence.CONFIRMED),
            ("Hypotheses", lambda n: n.type is NoteType.HYPOTHESIS or n.confidence is NoteConfidence.TENTATIVE),
            ("Temporary", lambda n: n.type is NoteType.TEMP),
        )
        lines = ["[Zhaoxi Working Notes]"]
        used: set[str] = set()
        budget = self.max_context_items
        for title, predicate in sections:
            selected = [note for note in notes if note.id not in used and predicate(note)][:budget]
            if selected:
                lines.extend(["", f"{title}:", *(f"- {note.content} [{note.source.value}/{note.confidence.value}]" for note in selected)])
                used.update(note.id for note in selected)
                budget -= len(selected)
            if budget <= 0:
                break
        if len(lines) == 1:
            lines.append("No active notes.")
        value = "\n".join(lines)
        logger.debug("action=snapshot_generated items=%d chars=%d timestamp=%s", len(used), len(value), self.now().isoformat())
        return value

    def diagnostics(self) -> dict:
        notes = self._refresh(self.now())
        return {"count": len(notes), "active_count": sum(note.status is NoteStatus.ACTIVE for note in notes),
                "snapshot": self.snapshot(), "items": [note.model_dump(mode="json") for note in notes[:50]]}

    def _refresh(self, now: datetime) -> list[WorkingNote]:
        notes = self.store.list()
        for note in notes:
            if note.status is NoteStatus.ACTIVE and note.expires_at and now >= self._aware(note.expires_at):
                note.status = NoteStatus.EXPIRED
                note.updated_at = now
                self.store.save(note)
                logger.info("action=expired id=%s type=%s timestamp=%s", note.id, note.type.value, now.isoformat())
        return notes

    def _aware(self, value: datetime) -> datetime:
        return value.astimezone(self.timezone) if value.tzinfo else value.replace(tzinfo=self.timezone)
