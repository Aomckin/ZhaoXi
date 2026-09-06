"""Notification sink and local inbox implementation."""

from abc import ABC, abstractmethod
from datetime import datetime

from zhaoxi.proactive.models import Delivery, DeliveryStatus
from zhaoxi.proactive.store import ProactiveStore


class NotificationSink(ABC):
    @abstractmethod
    async def deliver(self, delivery: Delivery, now: datetime) -> Delivery: ...


class InboxNotificationSink(NotificationSink):
    def __init__(self, store: ProactiveStore) -> None:
        self.store = store

    async def deliver(self, delivery: Delivery, now: datetime) -> Delivery:
        previous = await self.store.get_delivery(delivery.delivery_id)
        if previous and previous.delivered_at:
            return previous
        delivery.status = DeliveryStatus.DELIVERED
        delivery.delivered_at = now
        delivery.attempts += 1
        await self.store.save_delivery(delivery)
        return delivery

