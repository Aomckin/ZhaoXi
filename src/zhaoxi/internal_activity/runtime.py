"""Persistent v1.2.8 scheduler upgraded with a registry and presence policies."""
from __future__ import annotations
import asyncio
import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from zhaoxi.memory.models import aware_utc
from zhaoxi.reliability import provider_budget_scope
from .budget import TickBudget
from .models import ActivityResult, ActivityCategory, PresenceState
from .scheduler import ActivityScheduler
from .activities.legacy import build_registry, COGNITION, MEMORY, AGENDA, PROACTIVE, PERCEPTION_COGNITION, NAMES

logger = logging.getLogger("INTERNAL_ACTIVITY")

class InternalActivityRuntime:
    def __init__(self, agent, settings, path: str | Path) -> None:
        self.agent, self.settings = agent, settings
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS activity_state (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS activity_events (id INTEGER PRIMARY KEY, at TEXT, kind TEXT, name TEXT, detail TEXT)")
        self.registry = build_registry(settings)
        if getattr(settings, "presence_v2_enabled", False):
            from .activities.cognitive import register_cognitive
            from .activities.social import register_social
            register_cognitive(self.registry, settings)
            register_social(self.registry, settings)
        self.lock = asyncio.Lock()
        self.scheduler = ActivityScheduler(settings.internal_activity_max_llm_per_tick,
                                           settings.internal_activity_max_local_per_tick)
        self.state = self._load()
        self.proactive_check = None
        self.current_activity = None
        self.publish_status = None
        self._activity_task = None
        self._foreground_count = 0
        self._manual_social_confirmed = False
        previous = self.state.get("__runtime__", {})
        self.last_tick = previous.get("last_tick_at")
        self.last_selected = previous.get("selected", [])
        self.last_skipped = previous.get("skipped", {})
        self.last_candidates = previous.get("candidates", [])
        self.last_stream_cleanup = previous.get("last_stream_cleanup")
        self.last_activity = previous.get("last_activity")
        self.last_budget = previous.get("budget", {})
        self._daily = previous.get("daily", {})
        self._last_selected_name = previous.get("last_selected_name")
        self._streak = previous.get("streak", 0)

    def _connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def _load(self):
        with self._connect() as db:
            state = {name: json.loads(value) for name, value in db.execute("SELECT name, value FROM activity_state")}
        for spec in self.registry:
            item = state.setdefault(spec.name, {})
            for key, value in {"dirty": False, "last_run_at": None, "last_success_at": None,
                               "last_result": "NEVER", "failure_count": 0, "pending_signal_count": 0}.items():
                item.setdefault(key, value)
        return state

    def _save(self, name):
        with self._connect() as db:
            db.execute("INSERT INTO activity_state(name,value) VALUES (?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                       (name, json.dumps(self.state[name], ensure_ascii=False)))

    def _persist_runtime(self):
        self.state["__runtime__"] = {"last_tick_at": self.last_tick, "selected": self.last_selected,
            "skipped": self.last_skipped, "candidates": self.last_candidates,
            "last_stream_cleanup": self.last_stream_cleanup, "last_activity": self.last_activity,
            "budget": self.last_budget, "daily": self._daily,
            "last_selected_name": self._last_selected_name, "streak": self._streak}
        self._save("__runtime__")

    def event(self, kind, name=None, **detail):
        now = datetime.now(UTC).isoformat()
        with self._connect() as db:
            db.execute("INSERT INTO activity_events(at,kind,name,detail) VALUES (?,?,?,?)",
                       (now, kind, name, json.dumps(detail, ensure_ascii=False)))
            db.execute("DELETE FROM activity_events WHERE id < (SELECT COALESCE(MAX(id),0)-199 FROM activity_events)")
        logger.info("%s activity_name=%s detail=%s", kind, name, detail)

    @property
    def memory_service(self):
        auto = getattr(getattr(self.agent, "cognitive", None), "auto_memory", None)
        return getattr(self.agent, "memory_service", None) or (auto.service if auto else None)

    def presence(self):
        state = getattr(self.agent, "proactive_state", None)
        if self._foreground_count or getattr(state, "interacting", False):
            return PresenceState.ACTIVE
        interaction = getattr(state, "interaction", None)
        if interaction is None:
            return PresenceState.SEMI_ACTIVE
        presence = PresenceState(interaction.refresh(datetime.now(UTC)))
        if getattr(self.settings, "presence_sleep_enabled", False) and not interaction.debug_forced_state and presence != PresenceState.ACTIVE:
            hour = datetime.now(ZoneInfo(getattr(self.settings, "proactive_timezone", "Asia/Shanghai"))).hour
            start, end = self.settings.presence_sleep_start_hour, self.settings.presence_sleep_end_hour
            sleeping = start <= hour < end if start < end else hour >= start or hour < end
            if sleeping:
                return PresenceState.SLEEP
        return presence

    def publish_presence(self):
        if self.publish_status is not None:
            self.publish_status({"type": "presence_activity", "presence": self.public_status()})

    def foreground_enter(self):
        self._foreground_count += 1
        self.publish_presence()
        if self.current_activity and self.registry.get(self.current_activity).preemptible and not getattr(self, "_social_committing", False):
            task = self._activity_task
            if task and not task.done():
                task.cancel()

    def foreground_exit(self):
        self._foreground_count = max(0, self._foreground_count - 1)
        self.publish_presence()

    def _interval(self, name):
        return timedelta(minutes=self.registry.get(name).min_interval)

    def _enabled(self, name):
        spec = self.registry.get(name)
        return bool(getattr(self.settings, spec.enabled_setting, False)) if spec.enabled_setting else True

    def _last(self, name, field):
        raw = self.state[name].get(field)
        return aware_utc(datetime.fromisoformat(raw)) if raw else None

    def _skip(self, name, reason, now=None):
        self.last_skipped[name] = reason
        self.event("ACTIVITY_SKIPPED", name, reason=reason)

    def _day(self):
        zone = ZoneInfo(getattr(self.settings, "proactive_timezone", "Asia/Shanghai"))
        day = datetime.now(zone).date().isoformat()
        if self._daily.get("day") != day:
            self._daily = {"day": day, "counts": {}}
        return self._daily["counts"]

    def daily_count(self, name):
        return self._day().get(name, 0)

    def record_daily(self, name):
        counts = self._day()
        counts[name] = counts.get(name, 0) + 1
        self._persist_runtime()

    def _pending_turns(self):
        stream = getattr(self.agent, "experience_stream", None)
        if stream is not None:
            marker = self.agent.current_cognition.state().last_processed_message_id
            return sum(e.actor_role == "OWNER" and e.content and
                       e.event_type.value in {"USER_MESSAGE", "EXTERNAL_MESSAGE"}
                       for e in stream.events_after(marker, limit=200))
        return 0

    async def _memory_due(self, now):
        auto = getattr(getattr(self.agent, "cognitive", None), "auto_memory", None)
        if auto is None or not auto.auto_consolidator.config.enabled:
            return False
        repository = auto.service.repository
        count = int(await repository.get_runtime("episodes_since_consolidation_check") or 0)
        raw = await repository.get_runtime("last_consolidation_check_at")
        last = aware_utc(datetime.fromisoformat(raw)) if raw else None
        if count < auto.auto_consolidator.config.after_episodes and (last is not None and
                now - last < timedelta(hours=auto.auto_consolidator.config.interval_hours)):
            return False
        return bool(await auto.auto_consolidator.prefilter())

    async def _candidates(self, now, forced):
        candidates = []
        presence = self.presence()
        v2 = getattr(self.settings, "presence_v2_enabled", False)
        for spec in self.registry:
            name = spec.name
            self.state.setdefault(name, {"dirty": False, "last_run_at": None, "last_success_at": None,
                "last_result": "NEVER", "failure_count": 0, "pending_signal_count": 0})
            if forced and name != forced:
                continue
            # Manual debug bypasses the due gate, never social authorization or caps.
            if not self._enabled(name) and (not forced or spec.category == ActivityCategory.SOCIAL):
                self._skip(name, "disabled", now)
                continue
            if (v2 or self._foreground_count) and (self._foreground_count or presence not in spec.presence_states):
                self._skip(name, "foreground" if self._foreground_count else "presence:" + presence.value, now)
                continue
            if spec.daily_limit_setting and self.daily_count(name) >= getattr(self.settings, spec.daily_limit_setting, 0):
                self._skip(name, "daily_budget", now)
                continue
            item = self.state[name]
            failures = item["failure_count"]
            last = self._last(name, "last_run_at")
            cooldown = self._interval(name) * (min(8, 2 ** (failures - 1)) if failures >= 2 else 1)
            if last and now - last < cooldown and (not forced or spec.category == ActivityCategory.SOCIAL):
                self._skip(name, "backoff" if failures >= 2 else "cooldown", now)
                continue
            try:
                due = await spec.candidate(self, now)
            except Exception as exc:
                item.update(last_run_at=now.isoformat(), last_result="FAILED",
                            failure_count=failures + 1, dirty=True, last_error=type(exc).__name__)
                self._save(name)
                self._skip(name, "candidate_error", now)
                self.event("ACTIVITY_FAILED", name, reason="candidate_check", error=type(exc).__name__)
                continue
            if forced and spec.category != ActivityCategory.SOCIAL:
                due = ("forced", due[1] if due else spec.cost_class.value)
            if not due:
                if name not in self.last_skipped:
                    self._skip(name, "clean", now)
                continue
            reason, kind = due
            if item["dirty"] and spec.category in {ActivityCategory.COGNITION, ActivityCategory.MEMORY, ActivityCategory.MAINTENANCE}:
                reason = "recovery"
            priority = 100 if reason in {"bootstrap", "recovery"} else spec.priority
            fatigue = min(20, item.get("selection_streak", 0) * 3) if name in getattr(self, "_previous_selected", set()) else 0
            candidates.append((priority - fatigue, name, kind, reason))
            self.event("ACTIVITY_CANDIDATE", name, reason=reason, priority=priority, fatigue=fatigue)
        self.last_candidates = [{"priority": p, "name": n, "cost": k, "reason": r} for p, n, k, r in candidates]
        return sorted(candidates, reverse=True)

    async def _execute(self, name, kind):
        return await self.registry.get(name).handler(self, kind)

    async def run_tick(self, *, force=None, confirm_social_write=False, manual=False):
        if force is not None and force not in self.registry:
            raise ValueError("unknown activity")
        if not self.settings.internal_activity_enabled and force is None:
            return []
        if self.lock.locked():
            return []
        async with self.lock:
            now = datetime.now(UTC)
            self._previous_selected = set(self.last_selected)
            self.last_tick, self.last_selected, self.last_skipped = now.isoformat(), [], {}
            self._manual_social_confirmed = bool((force or manual) and confirm_social_write)
            self._manual = bool(force or manual)
            budget = TickBudget(self.settings)
            self.event("ACTIVITY_TICK_START", presence=self.presence().value, forced=force)
            deliveries = []
            try:
                stream = getattr(self.agent, "experience_stream", None)
                last_cleanup = aware_utc(datetime.fromisoformat(self.last_stream_cleanup)) if self.last_stream_cleanup else None
                if stream is not None and (last_cleanup is None or now - last_cleanup >= timedelta(days=1)):
                    stream.clear_expired(now)
                    self.last_stream_cleanup = now.isoformat()
                candidates = await self._candidates(now, force)
                # Maintenance debt blocks leisure even when it cannot fit the budget.
                debt = any(spec.priority >= 60 and self._enabled(spec.name) and self.state[spec.name]["dirty"]
                           for spec in self.registry)
                for name, kind, reason, skipped in self.scheduler.select_registered(candidates, self.registry, budget,
                                                                                   maintenance_pending=debt):
                    spec = self.registry.get(name)
                    if getattr(self.settings, "presence_v2_enabled", False) and (self._foreground_count or self.presence() not in spec.presence_states):
                        self._skip(name, "foreground", now)
                        continue
                    if skipped:
                        self._skip(name, skipped, now)
                        continue
                    self.last_selected.append(name)
                    self.event("ACTIVITY_SELECTED", name, reason=reason)
                    item = self.state[name]
                    item["last_run_at"] = now.isoformat()
                    item["selection_streak"] = item.get("selection_streak", 0) + 1 if name in self._previous_selected else 1
                    self.current_activity = name
                    self.publish_presence()
                    self.event("ACTIVITY_STARTED", name)
                    try:
                        needs = TickBudget.resources(spec, kind)
                        with provider_budget_scope(needs.get("llm", 0), 6000):
                            self._activity_task = asyncio.create_task(self._execute(name, kind))
                            raw = await self._activity_task
                        if isinstance(raw, list):
                            result = ActivityResult(status="MESSAGE" if raw else "NO_MESSAGE", message_sent=bool(raw), deliveries=raw)
                        elif isinstance(raw, ActivityResult):
                            result = raw
                        else:
                            result = ActivityResult(status=raw, changed=raw == "UPDATE")
                        if result.status in {"FAILED", "REJECTED", "PENDING_BOOTSTRAP"}:
                            raise RuntimeError(result.status)
                        if result.message_sent and not (spec.can_message_user or spec.can_message_external):
                            raise RuntimeError("activity_message_forbidden")
                        result.cost = result.cost or dict(needs)
                        item.update(last_success_at=datetime.now(UTC).isoformat(), last_result=result.status,
                                    result=result.diagnostics(), failure_count=0, dirty=False, degraded=False)
                        item.pop("last_error", None)
                        deliveries.extend(result.deliveries)
                        self.last_activity = {"name": name, "label": spec.label, "at": now.isoformat(), **result.diagnostics()}
                        self._streak = self._streak + 1 if self._last_selected_name == name else 1
                        self._last_selected_name = name
                        if spec.daily_limit_setting and (spec.category != ActivityCategory.LEISURE or result.evidence_refs):
                            self.record_daily(name)
                        self.event("ACTIVITY_NOOP" if result.status in {"NO_CHANGE", "NO_MESSAGE", "SKIP"} else "ACTIVITY_SUCCESS",
                                   name, result=result.diagnostics())
                        if result.message_sent:
                            self.event("ACTIVITY_MESSAGE_SENT", name)
                    except asyncio.CancelledError:
                        item.update(last_result="PREEMPTED", dirty=True)
                        self.event("ACTIVITY_SKIPPED", name, reason="foreground_preemption")
                        if asyncio.current_task().cancelling():
                            raise
                    except Exception as exc:
                        failures = item["failure_count"] + 1
                        item.update(last_result="FAILED", failure_count=failures, dirty=True,
                                    last_error=type(exc).__name__, degraded=failures >= 3)
                        self.event("ACTIVITY_FAILED", name, error=type(exc).__name__)
                    finally:
                        self.current_activity, self._activity_task = None, None
                        self.publish_presence()
                        self._save(name)
                if not self.last_selected:
                    self.event("ACTIVITY_NOOP", reason="NO_ACTIVITY")
            finally:
                self.last_budget = budget.diagnostics()
                self._manual_social_confirmed = False
                self._persist_runtime()
            return deliveries

    def public_status(self):
        name = self.current_activity if not self._foreground_count else None
        return {"current_presence": self.presence().value,
                "current_activity": self.registry.get(name).label if name else None,
                "status": self.registry.get(name).label if name else ("发呆中" if self.presence() == PresenceState.IDLE else None)}

    def diagnostics(self):
        now = datetime.now(UTC)
        self._day()
        for spec in self.registry:
            self.state.setdefault(spec.name, {"dirty": False, "last_run_at": None, "last_success_at": None,
                "last_result": "NEVER", "failure_count": 0, "pending_signal_count": 0})
        with self._connect() as db:
            rows = db.execute("SELECT at,kind,name,detail FROM activity_events ORDER BY id DESC LIMIT 80").fetchall()
        return {**self.public_status(), "current_activity": self.current_activity, "last_activity": self.last_activity,
            "last_tick_at": self.last_tick, "selected": self.last_selected, "skipped": self.last_skipped,
            "candidates": self.last_candidates, "tick_budget": self.last_budget,
            "daily_budgets": {"day": self._daily.get("day"), "counts": dict(self._day())},
            "timeline": [{"at": at, "kind": kind, "name": name, **json.loads(detail)} for at, kind, name, detail in rows],
            "activities": {s.name: {**self.state[s.name], "enabled": self._enabled(s.name), "priority": s.priority,
                "category": s.category.value, "cost_class": s.cost_class.value, "presence_states": sorted(s.presence_states),
                "min_interval_minutes": s.min_interval,
                "next_eligible_at": ((self._last(s.name, "last_run_at") + self._interval(s.name) *
                    (min(8, 2 ** (self.state[s.name]["failure_count"] - 1)) if self.state[s.name]["failure_count"] >= 2 else 1)) if self._last(s.name, "last_run_at") else now).isoformat(),
                "can_message_user": s.can_message_user, "can_message_external": s.can_message_external,
                "daily_limit": getattr(self.settings, s.daily_limit_setting, None) if s.daily_limit_setting else None}
                for s in self.registry}}
