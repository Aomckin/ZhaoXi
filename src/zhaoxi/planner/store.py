"""Planner task storage boundary."""

from __future__ import annotations

from abc import ABC, abstractmethod

from zhaoxi.errors import PlannerTaskNotFoundError
from zhaoxi.planner.models import Goal


class PlanStore(ABC):
    @abstractmethod
    async def save(self, goal: Goal) -> None: ...

    @abstractmethod
    async def get(self, goal_id: str) -> Goal | None: ...

    @abstractmethod
    async def list(self) -> list[Goal]: ...

    @abstractmethod
    def list_sync(self) -> list[Goal]:
        """Read goals during synchronous runtime startup, including permission waits."""
        ...


class InMemoryPlanStore(PlanStore):
    def __init__(self) -> None:
        self._goals: dict[str, Goal] = {}

    async def save(self, goal: Goal) -> None:
        self._goals[goal.id] = goal.model_copy(deep=True)

    async def get(self, goal_id: str) -> Goal | None:
        goal = self._goals.get(goal_id)
        return goal.model_copy(deep=True) if goal else None

    async def require(self, goal_id: str) -> Goal:
        goal = await self.get(goal_id)
        if goal is None:
            raise PlannerTaskNotFoundError(f"没有找到任务 {goal_id}。")
        return goal

    async def list(self) -> list[Goal]:
        return self.list_sync()

    def list_sync(self) -> list[Goal]:
        return [goal.model_copy(deep=True) for goal in self._goals.values()]
