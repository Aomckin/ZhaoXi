"""SQLite persistence for Reflection records."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from zhaoxi.reflection.models import ReflectionKind, ReflectionRecord
from zhaoxi.reflection.repository import ReflectionRepository


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS reflections (
    reflection_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    period_label TEXT NOT NULL,
    status TEXT NOT NULL,
    revision INTEGER NOT NULL,
    supersedes_id TEXT,
    source_fingerprint TEXT NOT NULL,
    prompt_version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    record_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reflections_history
ON reflections(kind, period_label, revision DESC);
CREATE INDEX IF NOT EXISTS idx_reflections_fingerprint
ON reflections(kind, period_label, source_fingerprint, prompt_version, status);
"""


class SQLiteReflectionRepository(ReflectionRepository):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            if connection.execute("SELECT version FROM schema_version LIMIT 1").fetchone() is None:
                connection.execute("INSERT INTO schema_version(version) VALUES (1)")

    async def create(self, record: ReflectionRecord) -> ReflectionRecord:
        return await asyncio.to_thread(self._create, record)

    def _create(self, record: ReflectionRecord) -> ReflectionRecord:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO reflections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                self._values(record),
            )
        return record

    async def get(self, reflection_id: str) -> ReflectionRecord | None:
        return await asyncio.to_thread(self._get, reflection_id)

    def _get(self, reflection_id: str) -> ReflectionRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM reflections WHERE reflection_id=?", (reflection_id,)
            ).fetchone()
        return ReflectionRecord.model_validate_json(row["record_json"]) if row else None

    async def save(self, record: ReflectionRecord) -> ReflectionRecord:
        return await asyncio.to_thread(self._save, record)

    def _save(self, record: ReflectionRecord) -> ReflectionRecord:
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE reflections SET kind=?, period_label=?, status=?, revision=?,
                supersedes_id=?, source_fingerprint=?, prompt_version=?, created_at=?,
                updated_at=?, record_json=? WHERE reflection_id=?""",
                (*self._values(record)[1:], record.reflection_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(f"Reflection 不存在：{record.reflection_id}")
        return record

    async def find_completed(
        self, kind: ReflectionKind, period_label: str, source_fingerprint: str, prompt_version: int
    ) -> ReflectionRecord | None:
        return await asyncio.to_thread(
            self._find_completed, kind, period_label, source_fingerprint, prompt_version
        )

    def _find_completed(
        self, kind: ReflectionKind, period_label: str, source_fingerprint: str, prompt_version: int
    ) -> ReflectionRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT record_json FROM reflections WHERE kind=? AND period_label=?
                AND source_fingerprint=? AND prompt_version=? AND status IN ('completed','partial')
                ORDER BY revision DESC LIMIT 1""",
                (kind.value, period_label, source_fingerprint, prompt_version),
            ).fetchone()
        return ReflectionRecord.model_validate_json(row["record_json"]) if row else None

    async def list(self, limit: int = 20) -> list[ReflectionRecord]:
        return await asyncio.to_thread(self._list, limit)

    def _list(self, limit: int) -> list[ReflectionRecord]:
        if limit < 1 or limit > 1000:
            raise ValueError("limit 必须在 1 到 1000 之间")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT record_json FROM reflections ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [ReflectionRecord.model_validate_json(row["record_json"]) for row in rows]

    @staticmethod
    def _values(record: ReflectionRecord) -> tuple[object, ...]:
        return (
            record.reflection_id,
            record.kind.value,
            record.period.label,
            record.status.value,
            record.revision,
            record.supersedes_id,
            record.source_fingerprint,
            record.prompt_version,
            record.created_at.isoformat(),
            record.updated_at.isoformat(),
            record.model_dump_json(),
        )
