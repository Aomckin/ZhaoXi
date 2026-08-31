"""SQLite persistence for proactive events, schedules, and deliveries."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path

from zhaoxi.proactive.models import Delivery, ProactiveEvent, Schedule
from zhaoxi.proactive.store import ProactiveStore


class SQLiteProactiveStore(ProactiveStore):
    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_version (component TEXT PRIMARY KEY, version INTEGER NOT NULL)"
            )
            row = connection.execute(
                "SELECT version FROM schema_version WHERE component='proactive'"
            ).fetchone()
            if row and row[0] > self.SCHEMA_VERSION:
                raise RuntimeError("Proactive 数据库版本高于当前程序支持版本。")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS proactive_events (
                    event_id TEXT PRIMARY KEY,
                    dedupe_key TEXT UNIQUE,
                    status TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS proactive_schedules (
                    schedule_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL,
                    next_fire_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS proactive_deliveries (
                    delivery_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    subscription_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    available_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    UNIQUE(event_id, subscription_id)
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_proactive_schedule_due ON proactive_schedules(enabled, next_fire_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_proactive_delivery_time ON proactive_deliveries(available_at DESC)"
            )
            connection.execute(
                "INSERT OR REPLACE INTO schema_version(component, version) VALUES('proactive', ?)",
                (self.SCHEMA_VERSION,),
            )

    async def add_event(self, event: ProactiveEvent) -> bool:
        return await asyncio.to_thread(self._add_event_sync, event.model_copy(deep=True))

    def _add_event_sync(self, event: ProactiveEvent) -> bool:
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO proactive_events(event_id, dedupe_key, status, occurred_at, payload) VALUES(?, ?, ?, ?, ?)",
                    (event.event_id, event.dedupe_key, event.status.value, event.occurred_at.isoformat(), event.model_dump_json()),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    async def get_event(self, event_id: str) -> ProactiveEvent | None:
        return await asyncio.to_thread(self._get_event_sync, event_id)

    def _get_event_sync(self, event_id: str) -> ProactiveEvent | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM proactive_events WHERE event_id=?", (event_id,)
            ).fetchone()
        return ProactiveEvent.model_validate_json(row[0]) if row else None

    async def save_schedule(self, schedule: Schedule) -> None:
        await asyncio.to_thread(self._save_schedule_sync, schedule.model_copy(deep=True))

    def _save_schedule_sync(self, schedule: Schedule) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO proactive_schedules(schedule_id, enabled, next_fire_at, payload)
                   VALUES(?, ?, ?, ?)
                   ON CONFLICT(schedule_id) DO UPDATE SET
                     enabled=excluded.enabled, next_fire_at=excluded.next_fire_at, payload=excluded.payload""",
                (schedule.schedule_id, int(schedule.enabled), schedule.next_fire_at.isoformat(), schedule.model_dump_json()),
            )

    async def get_schedule(self, schedule_id: str) -> Schedule | None:
        return await asyncio.to_thread(self._get_schedule_sync, schedule_id)

    def _get_schedule_sync(self, schedule_id: str) -> Schedule | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM proactive_schedules WHERE schedule_id=?", (schedule_id,)
            ).fetchone()
        return Schedule.model_validate_json(row[0]) if row else None

    async def due_schedules(self, now: datetime, limit: int) -> list[Schedule]:
        safe_limit = max(1, min(limit, 1000))
        return await asyncio.to_thread(self._due_schedules_sync, now, safe_limit)

    def _due_schedules_sync(self, now: datetime, limit: int) -> list[Schedule]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM proactive_schedules WHERE enabled=1 AND next_fire_at<=? ORDER BY next_fire_at LIMIT ?",
                (now.isoformat(), limit),
            ).fetchall()
        return [Schedule.model_validate_json(row[0]) for row in rows]

    async def list_schedules(self, limit: int = 100) -> list[Schedule]:
        safe_limit = max(1, min(limit, 1000))
        return await asyncio.to_thread(self._list_schedules_sync, safe_limit)

    def _list_schedules_sync(self, limit: int) -> list[Schedule]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM proactive_schedules ORDER BY next_fire_at LIMIT ?", (limit,)
            ).fetchall()
        return [Schedule.model_validate_json(row[0]) for row in rows]

    async def save_delivery(self, delivery: Delivery) -> bool:
        return await asyncio.to_thread(self._save_delivery_sync, delivery.model_copy(deep=True))

    def _save_delivery_sync(self, delivery: Delivery) -> bool:
        try:
            with self._connect() as connection:
                connection.execute(
                    """INSERT INTO proactive_deliveries(delivery_id, event_id, subscription_id, status, available_at, payload)
                       VALUES(?, ?, ?, ?, ?, ?)
                       ON CONFLICT(delivery_id) DO UPDATE SET
                         status=excluded.status, available_at=excluded.available_at, payload=excluded.payload""",
                    (delivery.delivery_id, delivery.event_id, delivery.subscription_id, delivery.status.value, delivery.available_at.isoformat(), delivery.model_dump_json()),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    async def list_deliveries(self, limit: int = 100) -> list[Delivery]:
        safe_limit = max(1, min(limit, 1000))
        return await asyncio.to_thread(self._list_deliveries_sync, safe_limit)

    def _list_deliveries_sync(self, limit: int) -> list[Delivery]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM proactive_deliveries ORDER BY available_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [Delivery.model_validate_json(row[0]) for row in rows]

