"""Business rules for controlled long-term memory."""

import re

from zhaoxi.errors import MemoryNotFoundError
from zhaoxi.memory.models import (
    MemoryCreate,
    MemoryQuery,
    MemoryRecord,
    MemorySearchResult,
    MemoryStatus,
    MemoryUpdate,
    MemoryWriteResult,
    utc_now,
    MemoryKind,
)
from zhaoxi.memory.lifecycle import MemoryLifecyclePolicy
from zhaoxi.memory.repository import MemoryRepository


def normalize_memory_text(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", value.casefold())


class MemoryService:
    """Validate, deduplicate, search and forget memory records."""

    def __init__(
        self,
        repository: MemoryRepository,
        lifecycle_policy: MemoryLifecyclePolicy | None = None,
    ) -> None:
        self.repository = repository
        self.lifecycle_policy = lifecycle_policy or MemoryLifecyclePolicy()

    async def remember(self, value: MemoryCreate) -> MemoryWriteResult:
        normalized = normalize_memory_text(value.content)
        duplicate = await self.repository.find_by_normalized_content(normalized)
        if duplicate and duplicate.status == MemoryStatus.ACTIVE:
            return MemoryWriteResult(record=duplicate, created=False, duplicate=True)

        candidates = await self.search(MemoryQuery(text=value.content, kind=value.kind, limit=3))
        conflicts = [item.record for item in candidates if item.score >= 0.65]
        if conflicts and not value.supersedes_id:
            return MemoryWriteResult(
                record=conflicts[0],
                created=False,
                conflict_candidates=conflicts,
            )
        record = MemoryRecord(
            **value.model_dump(),
            normalized_content=normalized,
        )
        if value.supersedes_id:
            previous = await self.require(value.supersedes_id)
            previous.status = MemoryStatus.SUPERSEDED
            previous.updated_at = utc_now()
            await self.repository.save(previous)
        stored = await self.repository.create(record)
        return MemoryWriteResult(record=stored, created=True, conflict_candidates=conflicts)

    async def get(self, memory_id: str) -> MemoryRecord | None:
        return await self.repository.get(memory_id)

    async def require(self, memory_id: str) -> MemoryRecord:
        record = await self.get(memory_id)
        if record is None:
            raise MemoryNotFoundError(f"记忆不存在：{memory_id}")
        return record

    async def search(self, query: MemoryQuery) -> list[MemorySearchResult]:
        requested_statuses = list(query.statuses)
        repository_query = query.model_copy(deep=True)
        if query.text and requested_statuses == [MemoryStatus.ACTIVE]:
            repository_query.statuses = [MemoryStatus.ACTIVE, MemoryStatus.COLD]
            repository_query.limit = min(query.limit * 3, 100)
        results = await self.repository.search(repository_query)
        now = utc_now()
        visible: list[MemorySearchResult] = []
        default_active_search = requested_statuses == [MemoryStatus.ACTIVE]
        for item in results:
            record = item.record
            should_activate = (
                record.status == MemoryStatus.ACTIVE
                and MemoryStatus.ACTIVE in requested_statuses
            ) or (
                record.status == MemoryStatus.COLD
                and default_active_search
                and bool(query.text)
                and item.score > 0
            )
            if should_activate:
                self.lifecycle_policy.decay(record, now)
                self.lifecycle_policy.activate(record, now)
                record.updated_at = now
                await self.repository.save(record)
            if record.status in requested_statuses or (
                MemoryStatus.ACTIVE in requested_statuses and record.status == MemoryStatus.ACTIVE
            ):
                visible.append(item)
        return visible[: query.limit]

    async def update(self, memory_id: str, patch: MemoryUpdate) -> MemoryRecord:
        record = await self.require(memory_id)
        changes = patch.model_dump(exclude_unset=True)
        for key, value in changes.items():
            setattr(record, key, value)
        if "content" in changes:
            record.normalized_content = normalize_memory_text(record.content)
        record.updated_at = utc_now()
        return await self.repository.save(record)

    async def forget(self, memory_id: str) -> MemoryRecord:
        record = await self.require(memory_id)
        if record.status != MemoryStatus.FORGOTTEN:
            record.status = MemoryStatus.FORGOTTEN
            record.updated_at = utc_now()
            await self.repository.save(record)
        return record

    async def archive(self, memory_id: str) -> MemoryRecord:
        record = await self.require(memory_id)
        if record.pinned:
            return record
        if record.status not in {MemoryStatus.FORGOTTEN, MemoryStatus.SUPERSEDED}:
            record.status = MemoryStatus.ARCHIVED
            record.updated_at = utc_now()
            await self.repository.save(record)
        return record

    async def reactivate(self, memory_id: str) -> MemoryRecord:
        record = await self.require(memory_id)
        if record.status in {MemoryStatus.FORGOTTEN, MemoryStatus.SUPERSEDED}:
            return record
        if record.status in {MemoryStatus.COLD, MemoryStatus.ARCHIVED}:
            record.status = MemoryStatus.ACTIVE
        self.lifecycle_policy.activate(record)
        record.updated_at = utc_now()
        return await self.repository.save(record)

    async def set_pinned(self, memory_id: str, pinned: bool = True) -> MemoryRecord:
        record = await self.require(memory_id)
        record.pinned = pinned
        if pinned:
            record.importance = max(record.importance, 0.9)
            if record.status in {MemoryStatus.COLD, MemoryStatus.ARCHIVED}:
                record.status = MemoryStatus.ACTIVE
        record.updated_at = utc_now()
        return await self.repository.save(record)

    async def maintain(self, limit: int = 100) -> list[MemoryRecord]:
        results = await self.repository.search(
            MemoryQuery(
                statuses=[MemoryStatus.ACTIVE, MemoryStatus.COLD, MemoryStatus.ARCHIVED],
                limit=min(limit, 100),
            )
        )
        changed: list[MemoryRecord] = []
        now = utc_now()
        for item in results:
            record = item.record
            if self.lifecycle_policy.maintain(record, now):
                record.updated_at = now
                await self.repository.save(record)
                changed.append(record)
        return changed

    async def consolidate(
        self,
        memory_ids: list[str],
        content: str,
        *,
        tags: list[str] | None = None,
    ) -> MemoryRecord:
        unique_ids = list(dict.fromkeys(memory_ids))
        if len(unique_ids) < 2:
            raise ValueError("至少需要两条记忆才能进行 Consolidation。")
        records = [await self.require(memory_id) for memory_id in unique_ids]
        value = MemoryCreate(
            content=content,
            kind=MemoryKind.SEMANTIC,
            tags=tags or list(dict.fromkeys(tag for record in records for tag in record.tags)),
            importance=min(1.0, max(record.importance for record in records) + 0.1),
            relevance=max(record.relevance for record in records),
            source_type=records[0].source_type,
            source_ref="memory_consolidation",
            evidence_reference=",".join(unique_ids),
            metadata={"consolidated_from": unique_ids},
        )
        consolidated = MemoryRecord(
            **value.model_dump(), normalized_content=normalize_memory_text(value.content)
        )
        await self.repository.create(consolidated)
        now = utc_now()
        for record in records:
            if not record.pinned:
                record.status = MemoryStatus.ARCHIVED
                record.updated_at = now
                await self.repository.save(record)
        return consolidated
