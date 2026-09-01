"""Bounded multi-source Reflection evidence collection."""

from __future__ import annotations

from zhaoxi.reflection.models import EvidenceRef, ReflectionPeriod, SourceSnapshot, SourceStatus
from zhaoxi.reflection.sources import ReflectionSource


class ReflectionCollector:
    def __init__(
        self,
        sources: list[ReflectionSource],
        *,
        max_evidence: int = 200,
        max_evidence_chars: int = 40_000,
    ) -> None:
        if max_evidence < 1 or max_evidence_chars < 1:
            raise ValueError("Reflection evidence 预算必须大于零")
        self.sources = sources
        self.max_evidence = max_evidence
        self.max_evidence_chars = max_evidence_chars

    async def collect(self, period: ReflectionPeriod) -> list[SourceSnapshot]:
        snapshots: list[SourceSnapshot] = []
        for source in self.sources:
            try:
                snapshot = await source.collect(period)
            except Exception as exc:
                snapshot = SourceSnapshot(
                    source=source.name,
                    status=SourceStatus.UNAVAILABLE,
                    period=period,
                    error_code=type(exc).__name__,
                )
            snapshots.append(snapshot)
        self._apply_budget(snapshots)
        return snapshots

    def _apply_budget(self, snapshots: list[SourceSnapshot]) -> None:
        seen: set[tuple[str, str]] = set()
        count = 0
        chars = 0
        for snapshot in snapshots:
            kept: list[EvidenceRef] = []
            original_count = len(snapshot.evidence)
            for evidence in snapshot.evidence:
                identity = (evidence.source_name, evidence.content_hash)
                next_chars = chars + len(evidence.excerpt)
                if identity in seen:
                    continue
                if count >= self.max_evidence or next_chars > self.max_evidence_chars:
                    continue
                seen.add(identity)
                kept.append(evidence)
                count += 1
                chars = next_chars
            snapshot.evidence = kept
            if len(kept) < original_count and snapshot.status == SourceStatus.AVAILABLE:
                snapshot.status = SourceStatus.PARTIAL
                snapshot.error_code = "evidence_budget_exceeded"
            elif not kept and snapshot.status == SourceStatus.AVAILABLE:
                snapshot.status = SourceStatus.EMPTY

    @staticmethod
    def flatten(snapshots: list[SourceSnapshot]) -> list[EvidenceRef]:
        evidence = [item for snapshot in snapshots for item in snapshot.evidence]
        return sorted(evidence, key=lambda item: (item.occurred_at, item.evidence_id))
