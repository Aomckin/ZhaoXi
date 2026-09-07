"""Long-term memory persistence contracts."""

from abc import ABC, abstractmethod

from zhaoxi.memory.models import (
    MemoryCluster,
    MemoryEdge,
    MemoryEmbedding,
    MemoryEntity,
    MemoryQuery,
    MemoryRecord,
    MemorySearchResult,
)


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

    @abstractmethod
    async def list_records(self, query: MemoryQuery) -> list[MemoryRecord]: ...

    @abstractmethod
    async def save_cluster(self, cluster: MemoryCluster) -> MemoryCluster: ...

    @abstractmethod
    async def list_clusters(self) -> list[MemoryCluster]: ...

    @abstractmethod
    async def add_cluster_member(self, cluster_id: str, memory_id: str, score: float) -> None: ...

    @abstractmethod
    async def list_cluster_members(self, cluster_id: str) -> list[MemoryRecord]: ...

    @abstractmethod
    async def merge_clusters(self, source_id: str, target_id: str) -> None: ...

    @abstractmethod
    async def save_edge(self, edge: MemoryEdge) -> MemoryEdge: ...

    @abstractmethod
    async def edges_for(self, node_ids: list[str], min_weight: float = 0) -> list[MemoryEdge]: ...

    @abstractmethod
    async def save_embedding(self, embedding: MemoryEmbedding) -> MemoryEmbedding: ...

    @abstractmethod
    async def list_embeddings(self) -> list[MemoryEmbedding]: ...

    @abstractmethod
    async def diagnostics(self) -> dict[str, object]: ...

    @abstractmethod
    async def set_runtime(self, key: str, value: str) -> None: ...

    @abstractmethod
    async def get_runtime(self, key: str) -> str | None: ...

    @abstractmethod
    async def save_entity(self, entity: MemoryEntity) -> MemoryEntity: ...

    @abstractmethod
    async def list_entities(self) -> list[MemoryEntity]: ...
