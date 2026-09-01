"""Reflection persistence contract."""

from abc import ABC, abstractmethod

from zhaoxi.reflection.models import ReflectionKind, ReflectionRecord


class ReflectionRepository(ABC):
    @abstractmethod
    async def create(self, record: ReflectionRecord) -> ReflectionRecord: ...

    @abstractmethod
    async def get(self, reflection_id: str) -> ReflectionRecord | None: ...

    @abstractmethod
    async def save(self, record: ReflectionRecord) -> ReflectionRecord: ...

    @abstractmethod
    async def find_completed(
        self, kind: ReflectionKind, period_label: str, source_fingerprint: str, prompt_version: int
    ) -> ReflectionRecord | None: ...

    @abstractmethod
    async def list(self, limit: int = 20) -> list[ReflectionRecord]: ...
