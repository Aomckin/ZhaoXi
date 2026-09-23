"""SQLite persistence for agenda items."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from zhaoxi.agenda.models import AgendaItem


SCHEMA = """
CREATE TABLE IF NOT EXISTS agenda_items (
    id TEXT PRIMARY KEY,
    item_type TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    item_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agenda_status_updated
ON agenda_items(status, updated_at DESC);
"""


class SQLiteAgendaStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def save(self, item: AgendaItem) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO agenda_items(id, item_type, status, updated_at, item_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET item_type=excluded.item_type,
                status=excluded.status, updated_at=excluded.updated_at,
                item_json=excluded.item_json""",
                (item.id, item.type.value, item.status.value, item.updated_at.isoformat(), item.model_dump_json()),
            )

    def get(self, item_id: str) -> AgendaItem | None:
        with self._connect() as connection:
            row = connection.execute("SELECT item_json FROM agenda_items WHERE id=?", (item_id,)).fetchone()
        return AgendaItem.model_validate_json(row["item_json"]) if row else None

    def list(self) -> list[AgendaItem]:
        with self._connect() as connection:
            rows = connection.execute("SELECT item_json FROM agenda_items ORDER BY updated_at DESC").fetchall()
        return [AgendaItem.model_validate_json(row["item_json"]) for row in rows]
