"""Evidence source adapters for Reflection collection."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod

from zhaoxi.memory.models import MemoryQuery, MemoryStatus
from zhaoxi.memory.service import MemoryService
from zhaoxi.reflection.models import (
    EvidenceRef,
    ReflectionPeriod,
    SourceSnapshot,
    SourceStatus,
)


class ReflectionSource(ABC):
    name: str

    @abstractmethod
    async def collect(self, period: ReflectionPeriod) -> SourceSnapshot: ...


class MemoryReflectionSource(ReflectionSource):
    """Read eligible memories without activating or mutating lifecycle metadata."""

    name = "zhaoxi-memory"

    def __init__(self, service: MemoryService, *, limit: int = 100, max_excerpt_chars: int = 800) -> None:
        self.service = service
        self.limit = limit
        self.max_excerpt_chars = max_excerpt_chars

    async def collect(self, period: ReflectionPeriod) -> SourceSnapshot:
        results = await self.service.repository.search(
            MemoryQuery(
                statuses=[MemoryStatus.ACTIVE, MemoryStatus.COLD],
                limit=min(self.limit, 100),
            )
        )
        evidence: list[EvidenceRef] = []
        for item in results:
            record = item.record
            occurred_at = record.valid_from or record.created_at
            if not period.start_at <= occurred_at < period.end_at:
                continue
            if record.source_ref == "reflection" or record.metadata.get("derived_from_reflection"):
                continue
            excerpt = record.content[: self.max_excerpt_chars]
            digest = hashlib.sha256(record.content.encode("utf-8")).hexdigest()
            evidence.append(EvidenceRef(
                source_type="memory",
                source_name=self.name,
                source_record_id=record.id,
                occurred_at=occurred_at,
                title=record.summary or "Zhaoxi Memory",
                excerpt=excerpt,
                content_hash=digest,
                metadata={"kind": record.kind.value, "tags": record.tags},
            ))
        evidence.sort(key=lambda item: (item.occurred_at, item.evidence_id))
        return SourceSnapshot(
            source=self.name,
            status=SourceStatus.AVAILABLE if evidence else SourceStatus.EMPTY,
            period=period,
            evidence=evidence,
        )
