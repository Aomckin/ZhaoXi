"""Workflow run persistence boundary."""

from abc import ABC, abstractmethod

from zhaoxi.workflow.models import WorkflowRun


class WorkflowStore(ABC):
    @abstractmethod
    async def save(self, run: WorkflowRun) -> None: ...

    @abstractmethod
    async def get(self, run_id: str) -> WorkflowRun | None: ...

    @abstractmethod
    async def list(self, limit: int = 100) -> list[WorkflowRun]: ...


class InMemoryWorkflowStore(WorkflowStore):
    def __init__(self) -> None:
        self.values: dict[str, WorkflowRun] = {}

    async def save(self, run: WorkflowRun) -> None:
        self.values[run.id] = run.model_copy(deep=True)

    async def get(self, run_id: str) -> WorkflowRun | None:
        value = self.values.get(run_id)
        return value.model_copy(deep=True) if value else None

    async def require(self, run_id: str) -> WorkflowRun:
        value = await self.get(run_id)
        if value is None:
            raise KeyError(f"Workflow Run 不存在：{run_id}")
        return value

    async def list(self, limit: int = 100) -> list[WorkflowRun]:
        values = sorted(self.values.values(), key=lambda item: item.created_at, reverse=True)
        return [item.model_copy(deep=True) for item in values[:limit]]
