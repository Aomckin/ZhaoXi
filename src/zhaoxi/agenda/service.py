"""Agenda lifecycle, querying and compact context formatting."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

from zhaoxi.agenda.models import AgendaItem, AgendaStatus, AgendaType
from zhaoxi.agenda.sqlite import SQLiteAgendaStore

logger = logging.getLogger("AGENDA")
TERMINAL = {AgendaStatus.DONE, AgendaStatus.MISSED, AgendaStatus.CANCELLED, AgendaStatus.RESCHEDULED}


def _key(value: str) -> str:
    return re.sub(r"\s+|[，。！？,.!?]", "", value).casefold()


class AgendaService:
    def __init__(self, store: SQLiteAgendaStore, *, timezone: str = "Asia/Shanghai", max_context_items: int = 8,
                 clock: Callable[[], datetime] | None = None) -> None:
        self.store = store
        self.timezone = ZoneInfo(timezone)
        self.max_context_items = max_context_items
        self.clock = clock

    def now(self) -> datetime:
        value = self.clock() if self.clock else datetime.now(self.timezone)
        return value.astimezone(self.timezone) if value.tzinfo else value.replace(tzinfo=self.timezone)

    def add(self, *, type: AgendaType, title: str, start_at: datetime | None = None,
            end_at: datetime | None = None, due_at: datetime | None = None, priority: int = 0,
            note: str = "", source: str = "user", scope: str | None = None,
            condition: str | None = None, secondary: bool = False) -> tuple[AgendaItem, bool]:
        now = self.now()
        values = {"start_at": start_at, "end_at": end_at, "due_at": due_at}
        values = {name: self._aware(value) if value is not None else None for name, value in values.items()}
        current = self._refresh(now)
        for old in current:
            if old.status not in TERMINAL and old.type is type and _key(old.title) == _key(title):
                changed = old.model_copy(update={
                    **values, "priority": priority, "note": note, "source": source,
                    "scope": scope, "condition": condition, "secondary": secondary,
                    "updated_at": now,
                })
                self.store.save(changed)
                logger.info("action=updated id=%s type=%s timestamp=%s deduplicated=true", changed.id, changed.type.value, now.isoformat())
                return changed, False
        if type is AgendaType.FOCUS and not secondary:
            for old in current:
                if old.status not in TERMINAL and old.type is AgendaType.FOCUS and not old.secondary:
                    old.status = AgendaStatus.RESCHEDULED
                    old.updated_at = now
                    self.store.save(old)
        item = AgendaItem(type=type, title=title.strip(), priority=priority, note=note, source=source,
                          scope=scope, condition=condition, secondary=secondary, created_at=now,
                          updated_at=now, **values)
        self.store.save(item)
        logger.info("action=created id=%s type=%s timestamp=%s", item.id, item.type.value, now.isoformat())
        return item, True

    def update(self, item_id: str, **changes) -> AgendaItem:
        item = self.require(item_id)
        now = self.now()
        for name in ("start_at", "end_at", "due_at"):
            if name in changes and changes[name] is not None:
                changes[name] = self._aware(changes[name])
        if any(name in changes for name in ("start_at", "end_at", "due_at")) and item.status is AgendaStatus.MISSED:
            changes["status"] = AgendaStatus.PLANNED
        item = item.model_copy(update={**changes, "updated_at": now})
        item = AgendaItem.model_validate(item.model_dump())
        self.store.save(item)
        logger.info("action=updated id=%s type=%s timestamp=%s", item.id, item.type.value, now.isoformat())
        return item

    def complete(self, item_id: str) -> AgendaItem:
        return self._set_status(item_id, AgendaStatus.DONE)

    def cancel(self, item_id: str) -> AgendaItem:
        return self._set_status(item_id, AgendaStatus.CANCELLED)

    def _set_status(self, item_id: str, status: AgendaStatus) -> AgendaItem:
        item = self.require(item_id)
        now = self.now()
        item.status = status
        item.updated_at = now
        item.completed_at = now if status is AgendaStatus.DONE else None
        self.store.save(item)
        logger.info("action=%s id=%s type=%s timestamp=%s", status.value, item.id, item.type.value, now.isoformat())
        return item

    def require(self, item_id: str) -> AgendaItem:
        item = self.store.get(item_id)
        if item is None:
            raise ValueError("Agenda 项目不存在。")
        return item

    def list(self, filter: str = "upcoming", *, now: datetime | None = None) -> list[AgendaItem]:
        now = now or self.now()
        items = self._refresh(now)
        if filter == "all_recent":
            return items[:50]
        if filter == "completed":
            return [item for item in items if item.status is AgendaStatus.DONE][:50]
        if filter == "active":
            return [item for item in items if item.status in {AgendaStatus.PLANNED, AgendaStatus.ACTIVE}]
        if filter == "deadline":
            return [item for item in items if item.type is AgendaType.DEADLINE and item.status not in TERMINAL]
        if filter == "today":
            return [item for item in items if item.status not in TERMINAL and self._date_for(item) == now.date()]
        if filter == "overdue":
            return [item for item in items if item.status is AgendaStatus.MISSED]
        if filter != "upcoming":
            raise ValueError("Agenda filter 无效。")
        return [item for item in items if item.status in {AgendaStatus.PLANNED, AgendaStatus.ACTIVE}]

    def snapshot(self, *, now: datetime | None = None) -> str:
        now = now or self.now()
        items = self.list("active", now=now)
        focus = [item for item in items if item.type is AgendaType.FOCUS]
        active = [item for item in items if item.status is AgendaStatus.ACTIVE and item.type is not AgendaType.FOCUS]
        upcoming = sorted((item for item in items if item.type in {AgendaType.EVENT, AgendaType.WINDOW} and item.status is AgendaStatus.PLANNED), key=lambda x: x.start_at or now)
        deadlines = sorted((item for item in items if item.type is AgendaType.DEADLINE), key=lambda x: x.due_at or now)
        expectations = [item for item in items if item.type is AgendaType.EXPECTATION]
        lines = ["[Agenda]", f"Now: {now:%Y-%m-%d %H:%M %Z}"]
        budget = self.max_context_items
        def section(title: str, values: list[AgendaItem], render) -> None:
            nonlocal budget
            chosen = values[:budget]
            if chosen:
                lines.extend(["", f"{title}:", *(render(item) for item in chosen)])
                budget -= len(chosen)
        section("Mainline", focus, lambda x: f"→ {x.title}" + (" (secondary)" if x.secondary else ""))
        section("Active", active, lambda x: f"- {x.title}")
        section("Upcoming", upcoming, lambda x: f"- {self._time_label(x.start_at, now)} {x.title}")
        section("Deadlines", deadlines, lambda x: f"- {self._time_label(x.due_at, now)} {x.title}")
        section("Expectation", expectations, lambda x: f"- {(x.condition + ' → ') if x.condition else ''}{x.title}")
        if len(lines) == 2:
            lines.append("No active items.")
        value = "\n".join(lines)
        logger.debug("action=snapshot_generated items=%d chars=%d timestamp=%s", self.max_context_items - budget, len(value), now.isoformat())
        return value

    def diagnostics(self) -> dict:
        items = self._refresh(self.now())
        return {"count": len(items), "active_count": sum(item.status not in TERMINAL for item in items),
                "snapshot": self.snapshot(), "items": [item.model_dump(mode="json") for item in items[:50]]}

    def _refresh(self, now: datetime) -> list[AgendaItem]:
        items = self.store.list()
        for item in items:
            status = self._derived_status(item, now)
            if status is not item.status:
                item.status = status
                item.updated_at = now
                self.store.save(item)
                logger.info("action=%s id=%s type=%s timestamp=%s automatic=true", status.value, item.id, item.type.value, now.isoformat())
        return items

    def _derived_status(self, item: AgendaItem, now: datetime) -> AgendaStatus:
        if item.status in TERMINAL:
            return item.status
        if item.type is AgendaType.DEADLINE and item.due_at and now > self._aware(item.due_at):
            return AgendaStatus.MISSED
        if item.type is AgendaType.FOCUS and item.scope == "today" and item.created_at.date() < now.date():
            return AgendaStatus.MISSED
        if item.type is AgendaType.EVENT and item.start_at:
            start = self._aware(item.start_at)
            if item.end_at and start <= now <= self._aware(item.end_at):
                return AgendaStatus.ACTIVE
            if now > (self._aware(item.end_at) if item.end_at else start):
                return AgendaStatus.MISSED
        if item.type is AgendaType.WINDOW and item.start_at:
            start = self._aware(item.start_at)
            end = self._aware(item.end_at) if item.end_at else start
            if now > end:
                return AgendaStatus.MISSED
            if start <= now <= end:
                return AgendaStatus.ACTIVE
        return AgendaStatus.PLANNED

    def _aware(self, value: datetime) -> datetime:
        return value.astimezone(self.timezone) if value.tzinfo else value.replace(tzinfo=self.timezone)

    @staticmethod
    def _date_for(item: AgendaItem):
        value = item.start_at or item.due_at or item.created_at
        return value.date()

    @staticmethod
    def _time_label(value: datetime | None, now: datetime) -> str:
        if value is None:
            return ""
        if value.date() == now.date():
            return value.strftime("Today %H:%M")
        return value.strftime("%m-%d %H:%M")
