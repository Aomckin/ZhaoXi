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
)
from zhaoxi.memory.repository import MemoryRepository


def normalize_memory_text(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", value.casefold())


class MemoryService:
    """Validate, deduplicate, search and forget memory records."""

    def __init__(self, repository: MemoryRepository) -> None:
        self.repository = repository

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
        return await self.repository.search(query)

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
