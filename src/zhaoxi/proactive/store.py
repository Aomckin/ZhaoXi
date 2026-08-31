"""Persistence boundary for proactive state."""

from abc import ABC, abstractmethod
from datetime import datetime

from zhaoxi.proactive.models import Delivery, ProactiveEvent, Schedule


class ProactiveStore(ABC):
    @abstractmethod
    async def add_event(self, event: ProactiveEvent) -> bool: ...

    @abstractmethod
    async def get_event(self, event_id: str) -> ProactiveEvent | None: ...

    @abstractmethod
    async def save_schedule(self, schedule: Schedule) -> None: ...

    @abstractmethod
    async def get_schedule(self, schedule_id: str) -> Schedule | None: ...

    @abstractmethod
    async def due_schedules(self, now: datetime, limit: int) -> list[Schedule]: ...

    @abstractmethod
    async def list_schedules(self, limit: int = 100) -> list[Schedule]: ...

    @abstractmethod
    async def save_delivery(self, delivery: Delivery) -> bool: ...

    @abstractmethod
    async def list_deliveries(self, limit: int = 100) -> list[Delivery]: ...


class InMemoryProactiveStore(ProactiveStore):
    def __init__(self) -> None:
        self.events: dict[str, ProactiveEvent] = {}
        self.event_dedupe: dict[str, str] = {}
        self.schedules: dict[str, Schedule] = {}
        self.deliveries: dict[str, Delivery] = {}
        self.delivery_pairs: set[tuple[str, str]] = set()

    async def add_event(self, event: ProactiveEvent) -> bool:
        if event.event_id in self.events:
            return False
        if event.dedupe_key and event.dedupe_key in self.event_dedupe:
            return False
        self.events[event.event_id] = event.model_copy(deep=True)
        if event.dedupe_key:
            self.event_dedupe[event.dedupe_key] = event.event_id
        return True

    async def get_event(self, event_id: str) -> ProactiveEvent | None:
        value = self.events.get(event_id)
        return value.model_copy(deep=True) if value else None

    async def save_schedule(self, schedule: Schedule) -> None:
        self.schedules[schedule.schedule_id] = schedule.model_copy(deep=True)

    async def get_schedule(self, schedule_id: str) -> Schedule | None:
        value = self.schedules.get(schedule_id)
        return value.model_copy(deep=True) if value else None

    async def due_schedules(self, now: datetime, limit: int) -> list[Schedule]:
        values = [item for item in self.schedules.values() if item.enabled and item.next_fire_at <= now]
        values.sort(key=lambda item: item.next_fire_at)
        return [item.model_copy(deep=True) for item in values[:limit]]

    async def list_schedules(self, limit: int = 100) -> list[Schedule]:
        values = sorted(self.schedules.values(), key=lambda item: item.next_fire_at)
        return [item.model_copy(deep=True) for item in values[:limit]]

    async def save_delivery(self, delivery: Delivery) -> bool:
        pair = (delivery.event_id, delivery.subscription_id)
        if pair in self.delivery_pairs and delivery.delivery_id not in self.deliveries:
            return False
        self.delivery_pairs.add(pair)
        self.deliveries[delivery.delivery_id] = delivery.model_copy(deep=True)
        return True

    async def list_deliveries(self, limit: int = 100) -> list[Delivery]:
        values = sorted(self.deliveries.values(), key=lambda item: item.available_at, reverse=True)
        return [item.model_copy(deep=True) for item in values[:limit]]

