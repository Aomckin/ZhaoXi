"""SQLite persistence for working notes."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from zhaoxi.working_notes.models import WorkingNote


SCHEMA = """
CREATE TABLE IF NOT EXISTS working_notes (
    id TEXT PRIMARY KEY,
    note_type TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    note_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_working_notes_status_updated
ON working_notes(status, updated_at DESC);
"""


class SQLiteWorkingNotesStore:
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

    def save(self, note: WorkingNote) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO working_notes(id, note_type, status, updated_at, note_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET note_type=excluded.note_type,
                status=excluded.status, updated_at=excluded.updated_at,
                note_json=excluded.note_json""",
                (note.id, note.type.value, note.status.value, note.updated_at.isoformat(), note.model_dump_json()),
            )

    def get(self, note_id: str) -> WorkingNote | None:
        with self._connect() as connection:
            row = connection.execute("SELECT note_json FROM working_notes WHERE id=?", (note_id,)).fetchone()
        return WorkingNote.model_validate_json(row["note_json"]) if row else None

    def list(self) -> list[WorkingNote]:
        with self._connect() as connection:
            rows = connection.execute("SELECT note_json FROM working_notes ORDER BY updated_at DESC").fetchall()
        return [WorkingNote.model_validate_json(row["note_json"]) for row in rows]

    def delete(self, note_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM working_notes WHERE id=?", (note_id,))
        return cursor.rowcount > 0
