"""Gated batch decisions and durable delivery, independent from observation cadence."""
import logging
import json
from uuid import uuid4
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
        self.delivery_lock = asyncio.Lock()
        self.last_decision = None
        self.activity = None

    async def tick(self, now=None):
        async with self.lock:
            return await self._tick(now or datetime.now(UTC))

    async def poke(self):
        async with self.lock:
            now = datetime.now(UTC)
            state = self.heartbeat.state
            state.interaction.interact(now)
            beat = state.interaction.beat_loop
            beat.sync(now)
            beat.session.initiative_budget = max(1, beat.session.initiative_budget)
            history = await self.heartbeat.runtime.store.list_deliveries(1000)
            return await self._beat(now, now.astimezone(ZoneInfo(self.heartbeat.settings.proactive_timezone)), history, None, forced=True)

    async def _tick(self, now):
        started = monotonic()
        h = self.heartbeat
        store, runtime, state = h.runtime.store, h.runtime, h.state
        local_now = now.astimezone(ZoneInfo(h.settings.proactive_timezone))
        flushed = await runtime.flush_deferred(local_now, state, ordinary_cooldown_minutes=h.settings.proactive_cooldown_minutes)
        h.metrics.increment('proactive.deliveries', len(flushed))
        history = await store.list_deliveries(1000)
        last_spoken = max((d.delivered_at for d in history if d.delivered_at
                           and d.priority != Priority.INFO), default=None)
        beat = getattr(state.interaction, 'beat_loop', None)
        if beat:
            delivery = await self._beat(now, local_now, history, last_spoken)
            if delivery:
                return [*flushed, delivery]
        continuation = None if beat else getattr(h, 'continuation', None)
        candidate = continuation.candidate(now, state.interaction) if continuation else None
        if candidate is not None and not state.interacting:
            h.metrics.increment('proactive.continuation_decisions')
            result = await self.decision.decide_continuation(candidate, local_now, state)
            checked_at = now + timedelta(seconds=monotonic() - started)
            continuation.decided(checked_at, close=result.action == 'silent')
            if result.action == 'speak' and state.interaction.can_continue(
                checked_at,
                cooldown_minutes=continuation.cooldown_minutes,
                budget=continuation.budget,
            ):
                delivery = Delivery(
                    delivery_id=f'continuation-{candidate.opened_at.timestamp()}',
                    event_id=f'continuation-{candidate.opened_at.timestamp()}',
                    subscription_id='conversation-continuation',
                    event_type='conversation.continuation',
                    relevant_payload={'summary': candidate.summary},
                    priority=Priority.NOTICE,
                    content=result.content,
                    decision_reason='active_conversation_continuation',
                    available_at=checked_at,
                )
                await runtime.sink.deliver(delivery, checked_at)
                continuation.delivered(checked_at, state.interaction)
                h.metrics.increment('proactive.continuations')
                h.metrics.increment('proactive.deliveries')
                return [*flushed, delivery]
        # Reconcile a crash after durable delivery but before resolving its events.
        delivered_ids = {eid for d in history for eid in [d.event_id, *d.related_event_ids]}
        batch, output = [], list(flushed)
        for event in await h.buffer.ready(now):
            if event.attempts >= 2:
                await self.resolve([event])
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
        if h.presence:
            state.interaction.observe(await h.presence.sample(), checked_at)
        for provider in getattr(h, 'signal_providers', []):
            try:
                state.interaction.observe_signals(await provider.collect_signals(checked_at), checked_at)
            except Exception:
                h.metrics.increment('proactive.signal_provider_errors')
        focus_signal = state.interaction.signals.resolve('attention.focus', checked_at)
        h.focus_active = bool(focus_signal and focus_signal.value == 'active')
        gates = [score_event(e, checked_at.astimezone(ZoneInfo(h.settings.proactive_timezone)),
                            state, runtime.policy, last_spoken, h.settings.proactive_cooldown_minutes,
                            h.focus_active) for e in batch]
        facts_current = all(
            e.event_type != 'focus.long_running' or focus_signal is None or h.focus_active
            for e in batch
        )
        if not facts_current:
            await self.resolve(batch)
        elif result.action == 'speak' and all(g.hint == 'inbox' for g in gates):
            output.append(await self.deliver(batch, result.content, Priority.INFO, checked_at, 'away_inbox'))
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

    def _trace_beat(self, beat, **updates):
        self.beat_trace.update(updates)
        self.beat_trace['beat_scheduled'] = self.beat_trace['scheduled']
        self.beat_trace['gate_passed'] = not self.beat_trace['gated']
        beat.last_trace = dict(self.beat_trace)
        if beat.trace_history and beat.trace_history[-1]['id'] == self.beat_trace['id']:
            beat.trace_history[-1] = dict(self.beat_trace)
        else:
            beat.trace_history.append(dict(self.beat_trace))
        logging.getLogger('BEAT').info('%s', json.dumps(self.beat_trace, default=str))

    async def _beat(self, now, local_now, history, last_spoken, forced=False):
        h = self.heartbeat
        state = h.state
        beat = state.interaction.beat_loop
        beat.sync(now)
        self.beat_trace = {'id': uuid4().hex, 'observed_at': now.isoformat(),
            'session_started_at': beat.session.started_at.isoformat() if beat.session else None,
            'scheduled': bool(beat.session and beat.session.next_beat_at and now >= beat.session.next_beat_at),
            'gated': False, 'gate_reason': None, 'llm_called': False, 'llm_action': None,
            'forced': forced, 'model_error': None, 'llm_confidence': None, 'suppressed': False, 'suppression_reason': None, 'delivered': False}
        reason = beat.gate(now, state, last_spoken, forced=forced)
        activity = state.interaction.desktop_activity
        self.beat_trace['desktop'] = activity.diagnostics() if activity else None
        desktop = self.beat_trace['desktop'] or {}
        self.beat_trace.update(desktop_busy=beat.desktop_busy(now),
            keyboard_1m=desktop.get('keyboard_rate_1m'), keyboard_5m=desktop.get('keyboard_rate_5m'),
            mouse_1m=desktop.get('mouse_rate_1m'), foreground_process=desktop.get('foreground_process'),
            interruptibility=str(state.interaction.interruptibility))
        self.beat_trace['interruptibility_reason'] = getattr(state.interaction, 'interruptibility_reason', None)
        policy = h.runtime.policy
        local_time = local_now.time().replace(tzinfo=None)
        night = (local_time >= policy.night_start or local_time < policy.night_end) if policy.night_start > policy.night_end else policy.night_start <= local_time < policy.night_end
        if reason or (night and not forced):
            if night and beat.session:
                beat.session.last_silent_reason = 'night_mode'
            if beat.session:
                self._trace_beat(beat, gated=True, gate_reason=reason or 'night_mode')
            return None
        pending = await h.runtime.store.pending_events()
        if not forced and any(e.event_type == 'reminder.due' or e.priority == Priority.URGENT for e in pending):
            beat.session.last_silent_reason = 'priority_message_pending'
            self._trace_beat(beat, gated=True, gate_reason='priority_message_pending')
            return None
        token = beat.reserve(now)
        started = monotonic()
        h.metrics.increment('proactive.beat_decisions')
        self._trace_beat(beat, llm_called=True)
        result = await beat.decide(self.decision, local_now, history)
        self._trace_beat(beat, llm_action=None if beat.model_failure else result.action,
            llm_confidence=None if beat.model_failure else result.confidence, model_error=beat.model_failure,
            model_diagnostics=dict(beat.model_diagnostics))
        checked = now + timedelta(seconds=monotonic()-started)
        async with self.delivery_lock:
            return await self._send_beat(beat, result, token, checked, last_spoken, forced)

    async def _send_beat(self, beat, result, token, checked, last_spoken, forced=False):
        h = self.heartbeat
        state = h.state
        # Observe latest user, desktop and quiet state after network latency.
        reason = beat.gate(checked, state, last_spoken, sending=True, forced=forced)
        if not beat.session or token != (beat.session.started_at, beat.session.last_user_at):
            self._trace_beat(beat, suppressed=True, suppression_reason='conversation_changed')
            return None
        local = checked.astimezone(ZoneInfo(h.settings.proactive_timezone)).time().replace(tzinfo=None)
        policy = h.runtime.policy
        night = (local >= policy.night_start or local < policy.night_end) if policy.night_start > policy.night_end else policy.night_start <= local < policy.night_end
        if night and not forced:
            reason = 'night_mode'
        beat.record(result)
        if reason:
            beat.session.last_silent_reason = reason
            self._trace_beat(beat, suppressed=True, suppression_reason=reason)
            return None
        if result.action == 'SILENT':
            self._trace_beat(beat, suppression_reason=beat.model_failure or 'model_silent')
            return None
        delivery = Delivery(
            delivery_id=f'beat-{token[0].timestamp()}-{beat.session.beat_count}',
            event_id=f'beat-{token[0].timestamp()}-{beat.session.beat_count}',
            subscription_id='conversation-beat', event_type='conversation.beat',
            relevant_payload={'summary': 'ACTIVE 对话中的自然续聊。'},
            priority=Priority.NOTICE, content=result.content,
            decision_reason='active_conversation_beat', available_at=checked,
        )
        try:
            await h.runtime.sink.deliver(delivery, checked)
        except Exception:
            self._trace_beat(beat, suppressed=True, suppression_reason='delivery_failed')
            raise
        self._trace_beat(beat, delivered=True)
        h.metrics.increment('proactive.deliveries')
        beat.sent(checked)
        from zhaoxi.core.message import Message, Role
        beat.conversation.add_delivery(Message(role=Role.ASSISTANT, content=result.content,
            delivery_id=delivery.delivery_id, timestamp=checked))
        h.metrics.increment('proactive.beat_deliveries')
        return delivery

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
                deliveries = await self.activity.run_tick() if self.activity is not None else await self.tick()
                for delivery in deliveries:
                    await publish({'type': 'proactive', 'delivery': delivery.model_dump(mode='json', exclude={'relevant_payload'})})
            except Exception:
                self.heartbeat.metrics.increment('proactive.worker_errors')
