"""Deterministic activation decay and natural memory lifecycle."""

from dataclasses import dataclass
from datetime import datetime, timezone

from zhaoxi.memory.models import MemoryRecord, MemoryStatus, aware_utc


@dataclass(slots=True)
class MemoryLifecyclePolicy:
    importance_keep_threshold: float = 0.75
    activation_active_threshold: float = 0.60
    importance_forget_threshold: float = 0.30
    activation_dormant_threshold: float = 0.20
    activation_decay_per_day: float = 0.01
    activation_access_boost: float = 0.12
    cold_dormant_after_days: float = 30
    dormant_archive_after_days: float = 90
    # v2 constructor compatibility. These names are not used as query relevance.
    relevance_active_threshold: float | None = None
    relevance_forget_threshold: float | None = None
    relevance_decay_per_day: float | None = None
    relevance_access_boost: float | None = None
    cold_archive_after_days: float | None = None

    def __post_init__(self) -> None:
        if self.relevance_active_threshold is not None:
            self.activation_active_threshold = self.relevance_active_threshold
        if self.relevance_forget_threshold is not None:
            self.activation_dormant_threshold = self.relevance_forget_threshold
        if self.relevance_decay_per_day is not None:
            self.activation_decay_per_day = self.relevance_decay_per_day
        if self.relevance_access_boost is not None:
            self.activation_access_boost = self.relevance_access_boost
        if self.cold_archive_after_days is not None:
            self.cold_dormant_after_days = self.cold_archive_after_days

    def decay(self, record: MemoryRecord, now: datetime | None = None) -> bool:
        now = aware_utc(now or datetime.now(timezone.utc))
        stored_basis = record.metadata.get("activation_decayed_at")
        basis = aware_utc(datetime.fromisoformat(stored_basis)) if stored_basis else max(
            value for value in (record.accessed_at, record.updated_at, record.created_at) if value
        )
        elapsed_days = max((now - basis).total_seconds() / 86_400, 0)
        value = max(0.0, record.activation - elapsed_days * self.activation_decay_per_day)
        changed = abs(value - record.activation) >= 0.0001
        record.activation = round(value, 4)
        if changed:
            record.metadata["activation_decayed_at"] = now.isoformat()
        return changed

    def classify(self, record: MemoryRecord, now: datetime | None = None) -> MemoryStatus:
        now = aware_utc(now or datetime.now(timezone.utc))
        if record.status in {MemoryStatus.SUPERSEDED, MemoryStatus.FORGOTTEN}:
            return record.status
        if record.activation >= self.activation_active_threshold:
            return MemoryStatus.ACTIVE
        if record.pinned or record.importance >= self.importance_keep_threshold:
            return MemoryStatus.COLD
        age_days = (now - record.created_at).total_seconds() / 86_400
        inactive_days = (now - record.updated_at).total_seconds() / 86_400
        if record.status == MemoryStatus.ACTIVE:
            return MemoryStatus.COLD
        if record.status == MemoryStatus.DORMANT and inactive_days >= self.dormant_archive_after_days:
            return MemoryStatus.ARCHIVED
        if record.status == MemoryStatus.COLD and age_days >= self.dormant_archive_after_days and inactive_days >= self.cold_dormant_after_days:
            return MemoryStatus.ARCHIVED
        if record.status == MemoryStatus.COLD and inactive_days >= self.cold_dormant_after_days:
            return MemoryStatus.DORMANT
        if record.status in {MemoryStatus.DORMANT, MemoryStatus.ARCHIVED}:
            return record.status
        return MemoryStatus.COLD

    def maintain(self, record: MemoryRecord, now: datetime | None = None) -> bool:
        changed = self.decay(record, now)
        target = self.classify(record, now)
        if target != record.status:
            record.status = target
            record.updated_at = now or datetime.now(timezone.utc)
            changed = True
        return changed

    def activate(self, record: MemoryRecord, now: datetime | None = None, amount: float | None = None) -> None:
        now = aware_utc(now or datetime.now(timezone.utc))
        record.activation = min(1.0, record.activation + (amount or self.activation_access_boost))
        record.access_count += 1
        record.accessed_at = now
        if record.status in {MemoryStatus.COLD, MemoryStatus.DORMANT}:
            record.status = MemoryStatus.ACTIVE
