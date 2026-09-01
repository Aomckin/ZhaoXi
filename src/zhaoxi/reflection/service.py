"""Reflection orchestration, idempotency and failure-state handling."""

import hashlib
from datetime import UTC, datetime

from zhaoxi.reflection.citations import CitationValidator
from zhaoxi.reflection.collector import ReflectionCollector
from zhaoxi.reflection.generator import ReflectionGenerator
from zhaoxi.reflection.models import (
    ReflectionKind,
    ReflectionPeriod,
    ReflectionRecord,
    ReflectionStatus,
    SourceStatus,
)
from zhaoxi.reflection.repository import ReflectionRepository


class ReflectionService:
    def __init__(
        self,
        repository: ReflectionRepository,
        collector: ReflectionCollector,
        generator: ReflectionGenerator,
        *,
        prompt_version: int = 1,
    ) -> None:
        self.repository = repository
        self.collector = collector
        self.generator = generator
        self.prompt_version = prompt_version
        self.citations = CitationValidator()

    async def generate(
        self,
        kind: ReflectionKind,
        period: ReflectionPeriod,
        *,
        regenerate: bool = False,
    ) -> ReflectionRecord:
        snapshots = await self.collector.collect(period)
        evidence = self.collector.flatten(snapshots)
        fingerprint = self._fingerprint(snapshots)
        if not regenerate:
            existing = await self.repository.find_completed(
                kind, period.label, fingerprint, self.prompt_version
            )
            if existing:
                return existing

        previous = self._latest_for_period(await self.repository.list(100), kind, period)
        record = ReflectionRecord(
            kind=kind,
            period=period,
            status=ReflectionStatus.GENERATING,
            revision=(previous.revision + 1) if regenerate and previous else 1,
            supersedes_id=previous.reflection_id if regenerate and previous else None,
            source_snapshots=snapshots,
            source_fingerprint=fingerprint,
            prompt_version=self.prompt_version,
        )
        if not evidence:
            record.status = ReflectionStatus.PARTIAL
            record.summary = "该范围内没有足够资料生成回顾。"
            record.uncertainties = ["所有已配置来源均未返回可用证据。"]
            return await self.repository.create(record)
        await self.repository.create(record)
        try:
            generated = await self.generator.generate(period, evidence)
            self.citations.validate(generated.sections, evidence)
            record.summary = generated.summary
            record.sections = generated.sections
            record.uncertainties = generated.uncertainties
            degraded = any(snapshot.status in {
                SourceStatus.PARTIAL,
                SourceStatus.UNAVAILABLE,
                SourceStatus.INCOMPATIBLE,
            } for snapshot in snapshots)
            record.status = ReflectionStatus.PARTIAL if degraded else ReflectionStatus.COMPLETED
        except Exception:
            record.status = ReflectionStatus.FAILED
            record.summary = "证据已采集，但本次回顾生成失败，可以稍后重试。"
            record.uncertainties = ["生成器或引用校验失败。"]
            record.updated_at = datetime.now(UTC)
            await self.repository.save(record)
            raise
        record.updated_at = datetime.now(UTC)
        return await self.repository.save(record)

    @staticmethod
    def _fingerprint(snapshots) -> str:
        values = sorted(
            f"{item.source_name}:{item.source_record_id or ''}:{item.content_hash}"
            for snapshot in snapshots for item in snapshot.evidence
        )
        return hashlib.sha256("\n".join(values).encode("utf-8")).hexdigest()

    @staticmethod
    def _latest_for_period(records, kind, period):
        matches = [
            item for item in records
            if item.kind == kind and item.period.label == period.label
        ]
        return max(matches, key=lambda item: item.revision, default=None)
