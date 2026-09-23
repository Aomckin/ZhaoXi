"""Separate SQLite state. Legacy working-notes data is deliberately untouched."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import ShortTermMemoryState


class ShortTermMemoryStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS short_term_memory (id INTEGER PRIMARY KEY CHECK(id=1), state_json TEXT NOT NULL)")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def load(self) -> ShortTermMemoryState:
        with self._connect() as db:
            row = db.execute("SELECT state_json FROM short_term_memory WHERE id=1").fetchone()
        return ShortTermMemoryState.model_validate_json(row[0]) if row else ShortTermMemoryState()

    def save(self, state: ShortTermMemoryState) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO short_term_memory(id,state_json) VALUES (1,?) ON CONFLICT(id) DO UPDATE SET state_json=excluded.state_json",
                       (state.model_dump_json(),))
