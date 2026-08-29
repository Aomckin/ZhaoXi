"""Long-term memory persistence contracts."""

from abc import ABC, abstractmethod

from zhaoxi.memory.models import MemoryQuery, MemoryRecord, MemorySearchResult


class MemoryRepository(ABC):
    @abstractmethod
    async def create(self, record: MemoryRecord) -> MemoryRecord: ...

    @abstractmethod
    async def get(self, memory_id: str) -> MemoryRecord | None: ...

    @abstractmethod
    async def save(self, record: MemoryRecord) -> MemoryRecord: ...

    @abstractmethod
    async def search(self, query: MemoryQuery) -> list[MemorySearchResult]: ...

    @abstractmethod
    async def find_by_normalized_content(self, content: str) -> MemoryRecord | None: ...
