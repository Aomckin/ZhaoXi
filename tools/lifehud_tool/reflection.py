"""Read-only Life HUD evidence adapter for Zhaoxi Reflection."""

from __future__ import annotations

import hashlib

from zhaoxi.sdk import EvidenceRef, ReflectionPeriod, ReflectionSource, SourceSnapshot, SourceStatus

from tools.lifehud_tool.client import LifeHudClient


class LifeHudReflectionSource(ReflectionSource):
    name = "lifehud"

    def __init__(self, client: LifeHudClient, *, max_excerpt_chars: int = 800) -> None:
        self.client = client
        self.max_excerpt_chars = max_excerpt_chars

    async def collect(self, period: ReflectionPeriod) -> SourceSnapshot:
        days = max(1, min(30, (period.end_at.date() - period.start_at.date()).days))
        context = await self.client.recent(days)
        evidence = []
        for item in context.timeline:
            if not period.start_at <= item.occurredAt < period.end_at:
                continue
            excerpt = (item.summary or item.title)[: self.max_excerpt_chars]
            digest = hashlib.sha256(
                f"{item.eventId}:{item.occurredAt.isoformat()}:{excerpt}".encode("utf-8")
            ).hexdigest()
            evidence.append(EvidenceRef(
                source_type="lifehud",
                source_name=self.name,
                source_record_id=item.eventId,
                occurred_at=item.occurredAt,
                title=item.title,
                excerpt=excerpt,
                content_hash=digest,
                metadata={"type": item.type, "source": item.source},
            ))
        return SourceSnapshot(
            source=self.name,
            status=SourceStatus.AVAILABLE if evidence else SourceStatus.EMPTY,
            period=period,
            evidence=evidence,
        )
