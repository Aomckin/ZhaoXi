"""Event-to-notification proactive runtime."""

from datetime import datetime

from zhaoxi.proactive.conditions import evaluate
from zhaoxi.proactive.models import (
    Delivery,
    DeliveryStatus,
    PolicyAction,
    ProactiveEvent,
    Subscription,
)
from zhaoxi.proactive.notifications import NotificationSink
from zhaoxi.proactive.policy import InterruptPolicy, PolicyState
from zhaoxi.proactive.store import ProactiveStore


class ProactiveRuntime:
    def __init__(
        self,
        store: ProactiveStore,
        sink: NotificationSink,
        policy: InterruptPolicy,
        subscriptions: list[Subscription] | None = None,
    ) -> None:
        self.store = store
        self.sink = sink
        self.policy = policy
        self.subscriptions = subscriptions or []

    async def process(self, event: ProactiveEvent, now: datetime, state: PolicyState) -> list[Delivery]:
        results: list[Delivery] = []
        existing = await self.store.list_deliveries(1000)

        context = {"event": event.model_dump(mode="python"), "payload": event.payload}
        for subscription in self.subscriptions:
            if not subscription.enabled or subscription.event_type != event.event_type:
                continue
            if not evaluate(subscription.condition, context):
                continue
            previous = next((d for d in existing if d.event_id == event.event_id and d.subscription_id == subscription.subscription_id), None)
            if previous:
                results.append(previous)
                continue
            priority = event.priority or subscription.default_priority
            decision = self.policy.decide(event, now, state)
            content = subscription.notification_template.format_map(
                {"event_type": event.event_type, "source": event.source, "payload": event.payload}
            )
            delivery = Delivery(
                delivery_id=f"{event.event_id}:{subscription.subscription_id}",
                event_id=event.event_id,
                event_type=event.event_type,
                relevant_payload={"summary": str(event.payload.get("text", event.payload.get("summary", "")))[:600]},
                subscription_id=subscription.subscription_id,
                priority=priority,
                decision_reason=decision.reason,
                content=content,
                available_at=decision.defer_until or now,
            )
            if decision.action == PolicyAction.SUPPRESS:
                delivery.status = DeliveryStatus.SUPPRESSED
                await self.store.save_delivery(delivery)
            elif decision.action == PolicyAction.DEFER:
                delivery.status = DeliveryStatus.DEFERRED
                await self.store.save_delivery(delivery)
            else:
                await self.sink.deliver(delivery, now)
            results.append(delivery)
        return results

    async def flush_deferred(self, now: datetime, state: PolicyState) -> list[Delivery]:
        results = []
        for delivery in await self.store.list_deliveries(1000):
            if delivery.status != DeliveryStatus.DEFERRED or delivery.available_at > now:
                continue
            event = await self.store.get_event(delivery.event_id)
            if event is None:
                continue
            decision = self.policy.decide(event, now, state)
            if decision.action == PolicyAction.SUPPRESS:
                delivery.status = DeliveryStatus.SUPPRESSED
                await self.store.save_delivery(delivery)
            elif decision.action == PolicyAction.DEFER or state.interacting:
                continue
            else:
                results.append(await self.sink.deliver(delivery, now))
        return results
