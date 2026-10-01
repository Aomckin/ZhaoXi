"""Explainable runtime heat, independent of long-term importance."""
from dataclasses import dataclass
from datetime import datetime, timezone
from zhaoxi.memory.models import MemoryRecord, MemoryStatus, aware_utc


@dataclass(slots=True)
class MemoryLifecyclePolicy:
    importance_keep_threshold: float = 0.75
    activation_active_threshold: float = 0.60
    activation_dormant_threshold: float = 0.20
    activation_decay_per_day: float = 0.025
    activation_access_boost: float = 0.12
    cold_dormant_after_days: float = 30
    dormant_archive_after_days: float = 90

    @staticmethod
    def _history(record, now, reason, before):
        record.metadata["activation_history"] = [*record.metadata.get("activation_history", []),
            {"at": now.isoformat(), "reason": reason, "before": round(before, 4),
             "after": round(record.activation, 4)}][-20:]

    def decay(self, record: MemoryRecord, now: datetime | None = None) -> bool:
        now = aware_utc(now or datetime.now(timezone.utc))
        if record.status in {MemoryStatus.FORGOTTEN, MemoryStatus.SUPERSEDED}:
            return False
        basis = record.metadata.get("activation_decayed_at")
        basis = aware_utc(datetime.fromisoformat(basis)) if basis else max(
            value for value in (record.accessed_at, record.created_at) if value)
        days = max((now - basis).total_seconds() / 86400, 0)
        inactive = max((now - (record.accessed_at or record.created_at)).total_seconds() / 86400, 0)
        rate = self.activation_decay_per_day * (1.25 - 0.8 * record.importance)
        rate *= 0.75 if record.importance >= self.importance_keep_threshold else 1
        rate *= 1 + min(inactive / 90, 2)
        rate *= 0.7 if record.status in {MemoryStatus.DORMANT, MemoryStatus.ARCHIVED} else 1
        before = record.activation
        record.activation = round(max(0, before - days * rate), 4)
        changed = abs(before - record.activation) >= 0.0001
        if changed:
            record.metadata["activation_decayed_at"] = now.isoformat()
            self._history(record, now, "time_decay", before)
        return changed

    def classify(self, record: MemoryRecord, now: datetime | None = None) -> MemoryStatus:
        now = aware_utc(now or datetime.now(timezone.utc))
        if record.status in {MemoryStatus.SUPERSEDED, MemoryStatus.FORGOTTEN}:
            return record.status
        if record.status==MemoryStatus.ARCHIVED:
            return MemoryStatus.ARCHIVED
        if record.status==MemoryStatus.DORMANT and record.activation>=self.activation_active_threshold:
            return MemoryStatus.DORMANT
        if record.activation >= self.activation_active_threshold:
            return MemoryStatus.ACTIVE
        inactive = max((now - (record.accessed_at or record.created_at)).total_seconds() / 86400, 0)
        if record.pinned:
            return MemoryStatus.COLD
        if inactive >= self.dormant_archive_after_days and record.activation < self.activation_dormant_threshold:
            return MemoryStatus.ARCHIVED
        if inactive >= self.cold_dormant_after_days and record.activation < self.activation_dormant_threshold:
            return MemoryStatus.DORMANT
        return MemoryStatus.COLD

    def maintain(self, record: MemoryRecord, now: datetime | None = None) -> bool:
        now = aware_utc(now or datetime.now(timezone.utc))
        changed = self.decay(record, now)
        target = self.classify(record, now)
        if target != record.status:
            record.metadata["lifecycle_reason"] = f"{record.status.value}->{target.value}: heat and access age"
            record.status = target
            changed = True
        return changed

    def activate(self, record: MemoryRecord, now: datetime | None = None, amount: float | None = None,
                 *, direct: bool = True, reason: str = "selected") -> None:
        now = aware_utc(now or datetime.now(timezone.utc))
        if record.status in {MemoryStatus.FORGOTTEN, MemoryStatus.SUPERSEDED}:
            return
        self.decay(record, now)
        before = record.activation
        boost = self.activation_access_boost if amount is None else amount
        record.activation = min(0.98, record.activation + boost * (1 - record.activation))
        self._history(record, now, reason, before)
        if direct:
            record.access_count += 1
            record.accessed_at = now
            if record.activation>=self.activation_active_threshold:
                record.status=MemoryStatus.ACTIVE
        record.metadata["activation_decayed_at"] = now.isoformat()
        record.status = self.classify(record, now)
