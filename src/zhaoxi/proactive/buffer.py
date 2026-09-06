"""Bounded durable candidate buffer; historical keys remain deduplicated in the store."""
from datetime import timedelta
from hashlib import sha256
from zhaoxi.proactive.models import EventStatus, Priority


class EventBuffer:
    def __init__(self, store, seconds=300, capacity=200):
        self.store, self.seconds, self.capacity = store, seconds, capacity

    async def add(self, event):
        if event.dedupe_key:
            event.event_id = 'sensor-' + sha256(event.dedupe_key.encode()).hexdigest()
        if await self.store.get_event(event.event_id) is not None:
            return False
        if event.expires_at is None:
            event.expires_at = event.received_at + timedelta(hours=6)
        pending = await self.store.pending_events(self.capacity + 1)
        if len(pending) >= self.capacity:
            lowest = min(pending, key=lambda e: e.importance + e.urgency)
            if lowest.importance + lowest.urgency >= event.importance + event.urgency:
                event.status = EventStatus.HANDLED
            else:
                lowest.status = EventStatus.HANDLED
                await self.store.update_event(lowest)
        return await self.store.add_event(event)

    async def ready(self, now):
        pending = await self.store.pending_events(self.capacity)
        ready = []
        for event in pending:
            if event.expires_at and event.expires_at <= now:
                event.status = EventStatus.HANDLED
                await self.store.update_event(event)
                continue
            if event.next_decision_at and event.next_decision_at > now:
                continue
            immediate = event.event_type == 'reminder.due' or event.priority == Priority.URGENT
            if immediate or (now - event.received_at).total_seconds() >= self.seconds:
                ready.append(event)
        return ready
