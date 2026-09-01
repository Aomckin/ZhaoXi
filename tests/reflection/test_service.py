from datetime import UTC, datetime

import pytest

from zhaoxi.reflection.collector import ReflectionCollector
from zhaoxi.reflection.generator import GeneratedReflection, ReflectionGenerator
from zhaoxi.reflection.models import (
    EvidenceRef,
    ReflectionKind,
    ReflectionPoint,
    ReflectionSection,
    ReflectionStatus,
    SourceSnapshot,
    SourceStatus,
)
from zhaoxi.reflection.periods import PeriodResolver
from zhaoxi.reflection.service import ReflectionService
from zhaoxi.reflection.sources import ReflectionSource
from zhaoxi.reflection.sqlite import SQLiteReflectionRepository


class StaticSource(ReflectionSource):
    name = "static"

    def __init__(self, evidence=None):
        self.evidence = evidence or []

    async def collect(self, period):
        return SourceSnapshot(
            source=self.name,
            status=SourceStatus.AVAILABLE if self.evidence else SourceStatus.EMPTY,
            period=period,
            evidence=self.evidence,
        )


class FakeGenerator(ReflectionGenerator):
    def __init__(self, *, invalid=False):
        self.calls = 0
        self.invalid = invalid

    async def generate(self, period, evidence):
        self.calls += 1
        evidence_id = "missing" if self.invalid else evidence[0].evidence_id
        return GeneratedReflection(
            summary="今天完成了 Reflection 内核。",
            sections=[ReflectionSection(name="overview", points=[
                ReflectionPoint(
                    text="完成了 Reflection 内核。",
                    statement_type="fact",
                    evidence_ids=[evidence_id],
                )
            ])],
        )


def evidence():
    return EvidenceRef(
        evidence_id="e1",
        source_type="test",
        source_name="static",
        source_record_id="r1",
        occurred_at=datetime(2026, 9, 1, tzinfo=UTC),
        title="开发",
        excerpt="完成 Reflection 内核",
        content_hash="12345678",
    )


@pytest.mark.asyncio
async def test_service_generates_validated_idempotent_reflection(tmp_path):
    period = PeriodResolver().resolve(ReflectionKind.DAILY, reference=datetime.now(UTC))
    generator = FakeGenerator()
    service = ReflectionService(
        SQLiteReflectionRepository(tmp_path / "reflection.db"),
        ReflectionCollector([StaticSource([evidence()])]),
        generator,
    )
    first = await service.generate(ReflectionKind.DAILY, period)
    second = await service.generate(ReflectionKind.DAILY, period)
    assert first.status == ReflectionStatus.COMPLETED
    assert first.reflection_id == second.reflection_id
    assert generator.calls == 1


@pytest.mark.asyncio
async def test_service_regenerate_creates_revision(tmp_path):
    period = PeriodResolver().resolve(ReflectionKind.DAILY, reference=datetime.now(UTC))
    service = ReflectionService(
        SQLiteReflectionRepository(tmp_path / "reflection.db"),
        ReflectionCollector([StaticSource([evidence()])]),
        FakeGenerator(),
    )
    first = await service.generate(ReflectionKind.DAILY, period)
    second = await service.generate(ReflectionKind.DAILY, period, regenerate=True)
    assert second.revision == 2
    assert second.supersedes_id == first.reflection_id


@pytest.mark.asyncio
async def test_empty_sources_are_saved_as_honest_partial_result(tmp_path):
    period = PeriodResolver().resolve(ReflectionKind.DAILY, reference=datetime.now(UTC))
    generator = FakeGenerator()
    service = ReflectionService(
        SQLiteReflectionRepository(tmp_path / "reflection.db"),
        ReflectionCollector([StaticSource()]),
        generator,
    )
    result = await service.generate(ReflectionKind.DAILY, period)
    assert result.status == ReflectionStatus.PARTIAL
    assert "没有足够资料" in result.summary
    assert generator.calls == 0


@pytest.mark.asyncio
async def test_invalid_citation_marks_record_failed(tmp_path):
    period = PeriodResolver().resolve(ReflectionKind.DAILY, reference=datetime.now(UTC))
    repository = SQLiteReflectionRepository(tmp_path / "reflection.db")
    service = ReflectionService(
        repository,
        ReflectionCollector([StaticSource([evidence()])]),
        FakeGenerator(invalid=True),
    )
    with pytest.raises(ValueError, match="不存在"):
        await service.generate(ReflectionKind.DAILY, period)
    assert (await repository.list())[0].status == ReflectionStatus.FAILED
