"""Adapters retain v1.2.8 maintenance and proactive behavior."""
from datetime import timedelta
from zhaoxi.memory.models import aware_utc
from zhaoxi.reliability import provider_budget_scope
from ..models import ActivitySpec, ActivityCategory as Category, CostClass as Cost, PresenceState as Presence
from ..registry import ActivityRegistry

COGNITION = "current_cognition_consolidation"
MEMORY = "memory_maintenance"
AGENDA = "agenda_maintenance"
PROACTIVE = "proactive_check"
PERCEPTION_COGNITION = "perception_cognition"
NAMES = (COGNITION, MEMORY, AGENDA, PERCEPTION_COGNITION, PROACTIVE)

async def cognition_due(r, now):
    state = r.agent.current_cognition.state()
    stream = getattr(r.agent, "experience_stream", None)
    users = sum(e.actor_role == "OWNER" and e.event_type.value in {"USER_MESSAGE", "EXTERNAL_MESSAGE"}
                for e in stream.recent(200)) if stream else 0
    pending = r._pending_turns()
    r.state[COGNITION]["pending_signal_count"] = pending
    if not state.overview and not state.threads and users >= r.settings.current_cognition_bootstrap_min_turns:
        return "bootstrap", "llm"
    if (state.overview or state.threads) and pending >= r.settings.current_cognition_consolidation_min_turns:
        return "pending_turns", "llm"
    if r.state[COGNITION]["dirty"] and users:
        return "recovery", "llm"
    last = r._last(COGNITION, "last_success_at") or getattr(state, "updated_at", None)
    if (state.overview or state.threads) and last and now - aware_utc(last) >= timedelta(hours=r.settings.current_cognition_consolidation_max_hours):
        return "periodic", "llm"

async def perception_due(r, now):
    runtime = getattr(r.agent, "perception", None)
    pending = len(runtime.store.pending_snapshots(1)) if runtime else 0
    r.state[PERCEPTION_COGNITION]["pending_signal_count"] = pending
    return ("pending_snapshot", "llm") if pending else None

async def memory_due(r, now):
    if await r._memory_due(now):
        return "new_memories", "llm"
    if getattr(r.settings, "presence_v2_enabled", False):
        service = r.memory_service
        if service is None:
            return None
        from zhaoxi.memory.models import MemoryQuery, MemoryStatus
        rows = await service.repository.list_records(MemoryQuery(statuses=[MemoryStatus.ACTIVE, MemoryStatus.COLD, MemoryStatus.DORMANT], limit=1))
        if not rows:
            return None
    return "lifecycle_check", "local"

async def agenda_due(r, now):
    agenda = getattr(r.agent, "agenda", None)
    if not getattr(r.settings, "presence_v2_enabled", False):
        return "time_reconciliation", "local"
    if agenda and agenda.store.list():
        return "time_reconciliation", "local"

async def proactive_due(r, now):
    if r.presence() in {Presence.AWAY, Presence.SLEEP}:
        worker = getattr(r.agent, "proactive_worker", None)
        if worker:
            from zhaoxi.proactive.models import Priority
            ready = await worker.heartbeat.buffer.ready(now)
            if any(e.priority == Priority.URGENT or r.presence() == Presence.AWAY and e.event_type == "reminder.due" for e in ready):
                return "important_reminder", "local"
            from zhaoxi.proactive.models import DeliveryStatus
            if any(d.priority == Priority.URGENT and d.status == DeliveryStatus.DEFERRED and d.available_at <= now
                   for d in await worker.heartbeat.runtime.store.list_deliveries(100)):
                return "deferred_urgent_reminder", "local"
        return None
    if r.proactive_check is None:
        return None
    worker = getattr(r.agent, "proactive_worker", None)
    if getattr(r.settings, "presence_v2_enabled", False) and worker:
        h = worker.heartbeat
        if await h.buffer.ready(now):
            return "pending_proactive_event", "llm"
        from zhaoxi.proactive.models import DeliveryStatus
        if any(d.status == DeliveryStatus.DEFERRED and d.available_at <= now for d in await h.runtime.store.list_deliveries(100)):
            return "deferred_delivery", "local"
        beat = getattr(h.state.interaction, "beat_loop", None)
        if beat and beat.gate(now, h.state) is None:
            return "active_beat", "llm"
        return None
    return "presence_check", "llm"

async def cognition(r, kind):
    stream = getattr(r.agent, "experience_stream", None)
    if stream is None:
        return "SKIP"
    return await r.agent.current_cognition_maintainer.maintain_events(stream, background=True)

async def perception(r, kind):
    runtime = getattr(r.agent, "perception", None)
    return "UPDATE" if runtime and await runtime.process_pending_snapshot() else "NO_CHANGE"

async def memory(r, kind):
    auto = getattr(getattr(r.agent, "cognitive", None), "auto_memory", None)
    service = r.memory_service
    if service is None:
        return "SKIP"
    changes = await service.maintain(organize=False) if getattr(r.settings, "presence_v2_enabled", False) else await service.maintain()
    if auto is None or kind != "llm":
        return "UPDATE" if changes else "NO_CHANGE"
    before = await service.repository.get_runtime("last_consolidation_check_at")
    changed = await auto.auto_consolidator.maybe_run()
    if before == await service.repository.get_runtime("last_consolidation_check_at"):
        raise RuntimeError("memory_consolidation_failed")
    return "UPDATE" if changed or changes else "NO_CHANGE"

async def agenda(r, kind):
    before = [(x.id, x.status) for x in r.agent.agenda.store.list()]
    r.agent.agenda.list("all_recent")
    after = [(x.id, x.status) for x in r.agent.agenda.store.list()]
    return "UPDATE" if before != after else "NO_CHANGE"

async def proactive(r, kind):
    if r.presence() in {Presence.AWAY, Presence.SLEEP}:
        worker = getattr(r.agent, "proactive_worker", None)
        if worker is None:
            return []
        from zhaoxi.proactive.models import Priority
        from zoneinfo import ZoneInfo
        from datetime import UTC, datetime
        now = datetime.now(UTC)
        local = now.astimezone(ZoneInfo(r.settings.proactive_timezone))
        h = worker.heartbeat
        deliveries = await h.runtime.flush_deferred(local, h.state, priorities={Priority.URGENT})
        for event in await h.buffer.ready(now):
            if event.priority == Priority.URGENT or r.presence() == Presence.AWAY and event.event_type == "reminder.due":
                deliveries.extend(await h.runtime.process(event, local, h.state))
                await worker.resolve([event])
        return deliveries
    return await r.proactive_check() if r.proactive_check else []

def build_registry(settings):
    registry = ActivityRegistry()
    awake = frozenset({Presence.SEMI_ACTIVE, Presence.IDLE})
    quiet = frozenset({*awake, Presence.AWAY, Presence.SLEEP})
    definitions = [
        (COGNITION, Category.COGNITION, Cost.LLM_LIGHT, awake, 70, "current_cognition_consolidation", cognition, cognition_due, "收拾近期状态"),
        (MEMORY, Category.MAINTENANCE, Cost.LOCAL_HEAVY, awake, 60, "memory_maintenance", memory, memory_due, "整理记忆"),
        (AGENDA, Category.LOCAL, Cost.LOCAL_LIGHT, quiet, 90, "agenda_maintenance", agenda, agenda_due, "核对日程"),
        (PERCEPTION_COGNITION, Category.COGNITION, Cost.LLM_LIGHT, awake, 65, "external_cognition_ambient", perception, perception_due, "消化外界见闻"),
        (PROACTIVE, Category.PROACTIVE, Cost.LLM_LIGHT, frozenset(Presence), 50, "proactive_activity", proactive, proactive_due, "想想要不要找你"),
    ]
    for name, category, cost, states, priority, prefix, handler, candidate, label in definitions:
        interval = getattr(settings, prefix + "_min_interval_minutes", 0)
        if name == PROACTIVE:
            interval = 5
        registry.register(ActivitySpec(name, category, cost, states, priority, interval, handler, candidate,
            enabled_setting=prefix + "_enabled", can_message_user=name == PROACTIVE,
            label=label, preemptible=name != AGENDA))
    return registry
