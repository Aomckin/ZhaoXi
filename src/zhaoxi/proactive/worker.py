"""Gated batch decisions and durable delivery, independent from observation cadence."""
import asyncio
from time import monotonic
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo
from zhaoxi.proactive.models import Delivery, EventStatus, Priority
from zhaoxi.proactive.scoring import score_event


class DecisionWorker:
    def __init__(self, heartbeat, decision):
        self.heartbeat, self.decision = heartbeat, decision
        self.lock = asyncio.Lock()
        self.last_decision = None

    async def tick(self, now=None):
        async with self.lock:
            return await self._tick(now or datetime.now(UTC))

    async def _tick(self, now):
        started = monotonic()
        h = self.heartbeat
        store, runtime, state = h.runtime.store, h.runtime, h.state
        local_now = now.astimezone(ZoneInfo(h.settings.proactive_timezone))
        flushed = await runtime.flush_deferred(local_now, state)
        h.metrics.increment('proactive.deliveries', len(flushed))
        history = await store.list_deliveries(1000)
        last_spoken = max((d.delivered_at for d in history if d.delivered_at
                           and d.priority != Priority.INFO), default=None)
        # Reconcile a crash after durable delivery but before resolving its events.
        delivered_ids = {eid for d in history for eid in [d.event_id, *d.related_event_ids]}
        batch, output = [], list(flushed)
        for event in await h.buffer.ready(now):
            if event.attempts >= 2:
                await self.resolve([event])
                continue
            if event.event_type == 'focus.long_running':
                sources = [s for s in h.sensors if hasattr(s, 'active_focus_id')]
                if sources and all(s.healthy and s.active_focus_id != event.payload.get('focus_id') for s in sources):
                    await self.resolve([event])
                    continue
                if any(not s.healthy for s in sources):
                    continue
            if event.event_id in delivered_ids:
                await self.resolve([event])
                continue
            gate = score_event(event, local_now, state, runtime.policy, last_spoken,
                               h.settings.proactive_cooldown_minutes, h.focus_active)
            h.metrics.increment('proactive.gate_' + gate.hint)
            if gate.hint == 'defer':
                event.next_decision_at = gate.until
                await store.update_event(event)
            elif gate.hint == 'drop':
                await self.resolve([event])
            elif gate.hint == 'inbox':
                output.append(await self.deliver([event], str(event.payload.get('summary', '有一条新的生活动态。')),
                                                 Priority.INFO, now, 'inbox'))
            elif event.event_type == 'reminder.due':
                # Explicit reminders must survive unavailable models and skip ordinary aggregation/cooldown.
                deliveries = await runtime.process(event, local_now, state)
                output.extend(deliveries)
                await self.resolve([event])
                h.metrics.increment('proactive.deliveries', len(deliveries))
                last_spoken = max((d.delivered_at for d in deliveries if d.delivered_at
                                   and d.priority != Priority.INFO), default=last_spoken)
            elif len(batch) < 20:
                batch.append(event)
        eligible = []
        for event in batch:
            gate = score_event(event, local_now, state, runtime.policy, last_spoken,
                               h.settings.proactive_cooldown_minutes, h.focus_active)
            if gate.hint == 'defer':
                event.next_decision_at = gate.until
                await store.update_event(event)
            else:
                eligible.append(event)
        batch = eligible
        if not batch:
            return output
        # Bound even silent/failed decisions; events get at most two deferred attempts.
        if self.last_decision and now - self.last_decision < timedelta(minutes=5):
            return output
        self.last_decision = now
        for event in batch:
            event.attempts += 1
            event.next_decision_at = now + timedelta(minutes=30)
            await store.update_event(event)
        h.metrics.increment('proactive.llm_decisions')
        result = await self.decision.decide(batch, local_now, state)
        # User/quiet state can change while the network request is running.
        checked_at = now + timedelta(seconds=monotonic() - started)
        gates = [score_event(e, checked_at.astimezone(ZoneInfo(h.settings.proactive_timezone)),
                            state, runtime.policy, last_spoken, h.settings.proactive_cooldown_minutes,
                            h.focus_active) for e in batch]
        sources = [s for s in h.sensors if hasattr(s, 'active_focus_id')]
        facts_current = all(
            e.event_type != 'focus.long_running' or not sources or any(
                s.healthy and s.active_focus_id == e.payload.get('focus_id') for s in sources)
            for e in batch
        )
        if not facts_current:
            await self.resolve(batch)
        elif result.action == 'speak' and all(g.hint in {'candidate', 'urgent'} for g in gates):
            priority = Priority.URGENT if all(e.priority == Priority.URGENT for e in batch) else Priority.NOTICE
            output.append(await self.deliver(batch, result.content, priority, checked_at, 'tidal_speak'))
            h.metrics.increment('proactive.spoken')
        elif result.action == 'defer' or (result.action == 'speak' and any(g.hint == 'defer' for g in gates)):
            for event in batch:
                if event.attempts >= 2:
                    await self.resolve([event])
        else:
            await self.resolve(batch)
        return output

    async def resolve(self, events):
        for event in events:
            event.status = EventStatus.HANDLED
            await self.heartbeat.runtime.store.update_event(event)

    async def deliver(self, events, content, priority, now, reason):
        delivery = Delivery(
            delivery_id='tidal-' + events[0].event_id, event_id=events[0].event_id,
            related_event_ids=[e.event_id for e in events], subscription_id='tidal',
            event_type=events[0].event_type, relevant_payload={'summaries': [
                str(e.payload.get('summary', ''))[:600] for e in events]},
            priority=priority, content=content, decision_reason=reason, available_at=now,
        )
        await self.heartbeat.runtime.sink.deliver(delivery, now)
        await self.resolve(events)
        self.heartbeat.metrics.increment('proactive.deliveries')
        return delivery

    async def run(self, publish):
        while True:
            await self.heartbeat.updated.wait()
            self.heartbeat.updated.clear()
            try:
                for delivery in await self.tick():
                    await publish({'type': 'proactive', 'delivery': delivery.model_dump(mode='json', exclude={'relevant_payload'})})
            except Exception:
                self.heartbeat.metrics.increment('proactive.worker_errors')
