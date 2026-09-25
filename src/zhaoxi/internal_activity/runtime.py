"""Small persistent scheduler for background cognition, memory and agenda work."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic

from zhaoxi.core.message import Role
from zhaoxi.memory.models import aware_utc
from zhaoxi.reliability import provider_budget_scope
from .scheduler import ActivityScheduler

logger = logging.getLogger("INTERNAL_ACTIVITY")

COGNITION = "current_cognition_consolidation"
MEMORY = "memory_maintenance"
AGENDA = "agenda_maintenance"
PROACTIVE = "proactive_check"
NAMES = (COGNITION, MEMORY, AGENDA, PROACTIVE)


class InternalActivityRuntime:
    def __init__(self, agent, settings, path: str | Path) -> None:
        self.agent, self.settings = agent, settings
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS activity_state (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.lock = asyncio.Lock()
        self.scheduler = ActivityScheduler(settings.internal_activity_max_llm_per_tick,
                                           settings.internal_activity_max_local_per_tick)
        self.state = self._load()
        self.proactive_check = None
        previous = self.state.get("__runtime__", {})
        self.last_tick = previous.get("last_tick_at")
        self.last_selected: list[str] = previous.get("selected", [])
        self.last_skipped: dict[str, str] = previous.get("skipped", {})

    def _connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def _load(self) -> dict:
        with self._connect() as db:
            rows = db.execute("SELECT name, value FROM activity_state").fetchall()
        state = {name: json.loads(value) for name, value in rows}
        for name in NAMES:
            state.setdefault(name, {"dirty": False, "last_run_at": None, "last_success_at": None,
                                    "last_result": "NEVER", "failure_count": 0, "pending_signal_count": 0})
        return state

    def _save(self, name: str) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO activity_state(name,value) VALUES (?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                       (name, json.dumps(self.state[name], ensure_ascii=False)))

    def _interval(self, name: str) -> timedelta:
        minutes = {
            COGNITION: self.settings.current_cognition_consolidation_min_interval_minutes,
            MEMORY: self.settings.memory_maintenance_min_interval_minutes,
            AGENDA: self.settings.agenda_maintenance_min_interval_minutes,
            PROACTIVE: 0,
        }[name]
        return timedelta(minutes=minutes)

    def _enabled(self, name: str) -> bool:
        return bool({
            COGNITION: self.settings.current_cognition_consolidation_enabled,
            MEMORY: self.settings.memory_maintenance_enabled,
            AGENDA: self.settings.agenda_maintenance_enabled,
            PROACTIVE: self.settings.proactive_activity_enabled,
        }[name])

    def _last(self, name: str, field: str) -> datetime | None:
        raw = self.state[name].get(field)
        return datetime.fromisoformat(raw) if raw else None

    def _skip(self, name: str, reason: str, now: datetime) -> None:
        self.last_skipped[name] = reason
        logger.info("ACTIVITY_SKIPPED activity_name=%s reason=%s started_at=%s duration=0 result=SKIP",
                    name, reason, now.isoformat())

    def _pending_turns(self) -> int:
        messages = self.agent.conversation.messages
        marker = self.state[COGNITION].get("last_consolidated_user_id")
        users = [item for item in messages if item.role == Role.USER]
        ids = [item.message_id for item in users]
        return len(ids) - ids.index(marker) - 1 if marker in ids else len(ids)

    async def _memory_due(self, now: datetime) -> bool:
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

    async def _candidates(self, now: datetime, forced: str | None) -> list[tuple[int, str, str, str]]:
        candidates = []
        users = sum(item.role == Role.USER for item in self.agent.conversation.messages)
        cognition = self.agent.current_cognition.state()
        for name in NAMES:
            if forced and name != forced:
                continue
            if not self._enabled(name) and not forced:
                self._skip(name, "disabled", now)
                continue
            last = self._last(name, "last_run_at")
            failures = self.state[name]["failure_count"]
            cooldown = self._interval(name) * (min(8, 2 ** (failures - 1)) if failures >= 2 else 1)
            if not forced and last and now - last < cooldown:
                self._skip(name, "backoff" if failures >= 2 else "cooldown", now)
                if failures >= 2:
                    logger.info("ACTIVITY_BACKOFF activity_name=%s reason=failures started_at=%s duration=0 result=SKIP",
                                name, now.isoformat())
                continue
            reason = "forced" if forced else ""
            if name == COGNITION:
                pending = self._pending_turns()
                self.state[name]["pending_signal_count"] = pending
                if not forced:
                    if not cognition.narrative and users >= self.settings.current_cognition_bootstrap_min_turns:
                        reason = "bootstrap"
                    elif cognition.narrative and pending >= self.settings.current_cognition_consolidation_min_turns:
                        reason = "pending_turns"
                    elif self.state[name]["dirty"] and users:
                        reason = "recovery"
                    elif cognition.narrative and cognition.observations and self._last(name, "last_success_at") and now - self._last(name, "last_success_at") >= timedelta(hours=self.settings.current_cognition_consolidation_max_hours):
                        reason = "periodic"
                priority = 100 if reason == "bootstrap" else 70
                kind = "llm"
            elif name == MEMORY:
                try:
                    needs_model = await self._memory_due(now)
                except Exception as exc:
                    item = self.state[name]
                    item.update({"last_run_at": now.isoformat(), "last_result": "FAILED",
                                 "failure_count": item["failure_count"] + 1, "dirty": True,
                                 "last_error": type(exc).__name__})
                    self._save(name)
                    self._skip(name, "candidate_error", now)
                    logger.warning("ACTIVITY_FAILED activity_name=%s reason=candidate_check started_at=%s duration=0 result=%s",
                                   name, now.isoformat(), type(exc).__name__)
                    continue
                reason = reason or ("new_memories" if needs_model else "lifecycle_check")
                priority, kind = 60, "llm" if needs_model else "local"
            elif name == AGENDA:
                reason = reason or "time_reconciliation"
                priority, kind = 90, "local"
            else:
                reason = reason or ("presence_check" if self.proactive_check is not None else "")
                priority, kind = 50, "llm"
            if reason:
                candidates.append((priority, name, kind, reason))
            else:
                self._skip(name, "clean", now)
        return sorted(candidates, reverse=True)

    async def run_tick(self, *, force: str | None = None) -> list:
        if force is not None and force not in NAMES:
            raise ValueError("unknown activity")
        if not self.settings.internal_activity_enabled and force is None:
            return []
        async with self.lock:
            now = datetime.now(UTC)
            self.last_tick = now.isoformat()
            self.last_selected = []
            self.last_skipped = {}
            logger.info("ACTIVITY_TICK_START started_at=%s", self.last_tick)
            deliveries = []
            candidates = await self._candidates(now, force)
            for name, kind, reason, selected in self.scheduler.select(candidates, forced=bool(force)):
                if not selected:
                    self._skip(name, "budget", now)
                    continue
                self.last_selected.append(name)
                logger.info("ACTIVITY_SELECTED activity_name=%s reason=%s started_at=%s", name, reason, now.isoformat())
                started = monotonic()
                item = self.state[name]
                item["last_run_at"] = now.isoformat()
                try:
                    result = await self._execute(name, kind)
                    if name == PROACTIVE:
                        deliveries.extend(result)
                        result = "MESSAGE" if result else "NO_MESSAGE"
                    if result in {"FAILED", "REJECTED", "PENDING_BOOTSTRAP"}:
                        raise RuntimeError(result)
                    item.update({"last_success_at": datetime.now(UTC).isoformat(), "last_result": result,
                                 "failure_count": 0, "dirty": False, "degraded": False})
                    if name == COGNITION:
                        users = [m for m in self.agent.conversation.messages if m.role == Role.USER]
                        if users:
                            item["last_consolidated_user_id"] = users[-1].message_id
                    logger.info("ACTIVITY_SUCCESS activity_name=%s reason=%s started_at=%s duration=%.3f result=%s",
                                name, reason, now.isoformat(), monotonic() - started, result)
                except Exception as exc:
                    item.update({"last_result": "FAILED", "failure_count": item["failure_count"] + 1,
                                 "dirty": True, "last_error": type(exc).__name__,
                                 "degraded": item["failure_count"] + 1 >= 3})
                    logger.warning("ACTIVITY_FAILED activity_name=%s reason=%s started_at=%s duration=%.3f result=%s",
                                   name, reason, now.isoformat(), monotonic() - started, type(exc).__name__)
                self._save(name)
            self.state["__runtime__"] = {"last_tick_at": self.last_tick,
                                          "selected": self.last_selected, "skipped": self.last_skipped}
            self._save("__runtime__")
            return deliveries

    async def _execute(self, name: str, kind: str):
        if name == COGNITION:
            messages = self.agent.conversation.messages[-40:]
            if not any(item.role == Role.USER for item in messages):
                return "SKIP"
            provider = self.agent.current_cognition_maintainer.provider
            with provider_budget_scope(getattr(provider, "max_calls", 12),
                                       getattr(provider, "max_total_tokens", 100_000)):
                return await self.agent.current_cognition_maintainer.maintain(
                    messages, pending_override=messages, background=True)
        if name == MEMORY:
            auto = getattr(getattr(self.agent, "cognitive", None), "auto_memory", None)
            service = getattr(self.agent, "memory_service", None) or (auto.service if auto else None)
            if service is None:
                return "SKIP"
            local_changes = await service.maintain()
            if auto is None:
                return "UPDATE" if local_changes else "NO_CHANGE"
            before = await auto.service.repository.get_runtime("last_consolidation_check_at") if kind == "llm" else None
            changed = await auto.auto_consolidator.maybe_run() if kind == "llm" else False
            if kind == "llm" and before == await auto.service.repository.get_runtime("last_consolidation_check_at"):
                raise RuntimeError("memory_consolidation_failed")
            return "UPDATE" if changed or local_changes else "NO_CHANGE"
        if name == AGENDA:
            before = [(item.id, item.status) for item in self.agent.agenda.store.list()]
            self.agent.agenda.list("all_recent")
            after = [(item.id, item.status) for item in self.agent.agenda.store.list()]
            return "UPDATE" if before != after else "NO_CHANGE"
        if self.proactive_check is None:
            return []
        return await self.proactive_check()

    def diagnostics(self) -> dict:
        return {"last_tick_at": self.last_tick, "selected": self.last_selected,
                "skipped": self.last_skipped, "activities": {
                    name: {**self.state[name], "enabled": self._enabled(name),
                           "min_interval_minutes": int(self._interval(name).total_seconds() / 60),
                           "priority": {COGNITION: 70, MEMORY: 60, AGENDA: 90, PROACTIVE: 50}[name]}
                    for name in NAMES}}
