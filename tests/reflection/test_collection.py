from datetime import UTC, datetime, timedelta

import pytest

from zhaoxi.memory.models import MemoryCreate, MemoryStatus
from zhaoxi.memory.service import MemoryService
from zhaoxi.memory.sqlite import SQLiteMemoryRepository
from zhaoxi.reflection.citations import CitationError, CitationValidator
from zhaoxi.reflection.collector import ReflectionCollector
from zhaoxi.reflection.models import (
    EvidenceRef,
    ReflectionKind,
    ReflectionPoint,
    ReflectionSection,
    SourceSnapshot,
    SourceStatus,
)
from zhaoxi.reflection.periods import PeriodResolver
from zhaoxi.reflection.sources import MemoryReflectionSource, ReflectionSource


class FakeSource(ReflectionSource):
    def __init__(self, name, evidence=None, error=None):
        self.name = name
        self.evidence = evidence or []
        self.error = error

    async def collect(self, period):
        if self.error:
            raise self.error
        return SourceSnapshot(
            source=self.name,
            status=SourceStatus.AVAILABLE if self.evidence else SourceStatus.EMPTY,
            period=period,
            evidence=self.evidence,
        )


def make_evidence(source, excerpt, suffix):
    return EvidenceRef(
        evidence_id=f"e{suffix}",
        source_type="test",
        source_name=source,
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        title="test",
        excerpt=excerpt,
        content_hash=f"1234567{suffix}",
    )


@pytest.mark.asyncio
async def test_memory_source_filters_period_status_and_derived_records(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    period = PeriodResolver().resolve(
        ReflectionKind.DAILY, reference=datetime(2026, 9, 1, 8, tzinfo=UTC)
    )
    included = (await service.remember(MemoryCreate(
        content="今天开始实现 Reflection",
        valid_from=period.start_at + timedelta(hours=1),
    ))).record
    old = (await service.remember(MemoryCreate(
        content="昨天的记录",
        valid_from=period.start_at - timedelta(hours=1),
    ))).record
    forgotten = (await service.remember(MemoryCreate(
        content="不应再出现的记录",
        valid_from=period.start_at + timedelta(hours=2),
    ))).record
    forgotten.status = MemoryStatus.FORGOTTEN
    await service.repository.save(forgotten)
    await service.remember(MemoryCreate(
        content="由旧 Reflection 派生的摘要",
        valid_from=period.start_at + timedelta(hours=3),
        source_ref="reflection",
    ))
    snapshot = await MemoryReflectionSource(service).collect(period)
    assert [item.source_record_id for item in snapshot.evidence] == [included.id]
    assert old.id not in [item.source_record_id for item in snapshot.evidence]


@pytest.mark.asyncio
async def test_collector_isolates_failure_deduplicates_and_applies_budget():
    period = PeriodResolver().resolve(ReflectionKind.DAILY, reference=datetime.now(UTC))
    first = make_evidence("one", "12345", "1")
    duplicate = first.model_copy(update={"evidence_id": "duplicate"})
    overflow = make_evidence("two", "67890", "2")
    collector = ReflectionCollector([
        FakeSource("one", [first, duplicate, overflow]),
        FakeSource("broken", error=RuntimeError("secret details")),
    ], max_evidence=2, max_evidence_chars=9)
    snapshots = await collector.collect(period)
    assert [item.evidence_id for item in snapshots[0].evidence] == ["e1"]
    assert snapshots[0].status == SourceStatus.PARTIAL
    assert snapshots[1].status == SourceStatus.UNAVAILABLE
    assert snapshots[1].error_code == "RuntimeError"


def test_citation_validator_rejects_unknown_ids_and_question_citations():
    evidence = [make_evidence("one", "fact", "1")]
    validator = CitationValidator()
    validator.validate([
        ReflectionSection(name="overview", points=[
            ReflectionPoint(text="完成开发", statement_type="fact", evidence_ids=["e1"])
        ])
    ], evidence)
    with pytest.raises(CitationError, match="不存在"):
        validator.validate([
            ReflectionSection(name="overview", points=[
                ReflectionPoint(text="未知事实", statement_type="fact", evidence_ids=["missing"])
            ])
        ], evidence)
    with pytest.raises(CitationError, match="question"):
        validator.validate([
            ReflectionSection(name="questions", points=[
                ReflectionPoint(text="感受如何？", statement_type="question", evidence_ids=["e1"])
            ])
        ], evidence)
