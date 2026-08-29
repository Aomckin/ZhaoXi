"""Deterministic importance/relevance lifecycle policy."""

from dataclasses import dataclass
from datetime import datetime, timezone

from zhaoxi.memory.models import MemoryRecord, MemoryStatus


@dataclass(slots=True)
class MemoryLifecyclePolicy:
    """Centralized thresholds for decay and lifecycle classification."""

    importance_keep_threshold: float = 0.75
    relevance_active_threshold: float = 0.60
    importance_forget_threshold: float = 0.30
    relevance_forget_threshold: float = 0.20
    relevance_decay_per_day: float = 0.01
    relevance_access_boost: float = 0.15
    cold_archive_after_days: float = 30

    def decay(self, record: MemoryRecord, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        basis = max(
            value for value in (record.accessed_at, record.updated_at, record.created_at) if value
        )
        elapsed_days = max((now - basis).total_seconds() / 86_400, 0)
        value = max(0.0, record.relevance - elapsed_days * self.relevance_decay_per_day)
        changed = abs(value - record.relevance) >= 0.0001
        record.relevance = round(value, 4)
        return changed

    def classify(
        self, record: MemoryRecord, now: datetime | None = None
    ) -> MemoryStatus:
        now = now or datetime.now(timezone.utc)
        if record.status in {MemoryStatus.SUPERSEDED, MemoryStatus.FORGOTTEN}:
            return record.status
        if record.pinned:
            return (
                MemoryStatus.ACTIVE
                if record.relevance >= self.relevance_active_threshold
                else MemoryStatus.COLD
            )
        if record.importance >= self.importance_keep_threshold:
            return (
                MemoryStatus.ACTIVE
                if record.relevance >= self.relevance_active_threshold
                else MemoryStatus.COLD
            )
        if record.relevance >= self.relevance_active_threshold:
            return MemoryStatus.ACTIVE
        if (
            record.importance < self.importance_forget_threshold
            and record.relevance < self.relevance_forget_threshold
        ):
            if (
                record.status == MemoryStatus.COLD
                and (now - record.updated_at).total_seconds()
                >= self.cold_archive_after_days * 86_400
            ):
                return MemoryStatus.ARCHIVED
            if record.status == MemoryStatus.ARCHIVED:
                return MemoryStatus.ARCHIVED
            return MemoryStatus.COLD
        return MemoryStatus.COLD

    def maintain(self, record: MemoryRecord, now: datetime | None = None) -> bool:
        changed = self.decay(record, now)
        target = self.classify(record, now)
        if target != record.status:
            record.status = target
            changed = True
        return changed

    def activate(self, record: MemoryRecord, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        record.relevance = min(1.0, record.relevance + self.relevance_access_boost)
        record.access_count += 1
        record.accessed_at = now
        if record.status == MemoryStatus.COLD:
            record.status = MemoryStatus.ACTIVE
