"""Independent state store; legacy STM is read once as bootstrap reference only."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import CurrentCognitionState


class CurrentCognitionStore:
    def __init__(self, path: str | Path, *, legacy_stm_path: str | Path | None = None) -> None:
        self.path = Path(path)
        self.legacy_stm_path = Path(legacy_stm_path) if legacy_stm_path else None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS current_cognition (id INTEGER PRIMARY KEY CHECK(id=1), state_json TEXT NOT NULL)")

    def load(self) -> CurrentCognitionState:
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT state_json FROM current_cognition WHERE id=1").fetchone()
        return CurrentCognitionState.model_validate_json(row[0]) if row else CurrentCognitionState()

    def save(self, state: CurrentCognitionState) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO current_cognition(id,state_json) VALUES (1,?) ON CONFLICT(id) DO UPDATE SET state_json=excluded.state_json",
                       (state.model_dump_json(),))

    def legacy_reference(self) -> str:
        """Untrusted, bounded reference; never copies a legacy item into new state."""
        path = self.legacy_stm_path
        if path is None or not path.is_file():
            return ""
        try:
            uri = path.resolve().as_uri() + "?mode=ro"
            db = sqlite3.connect(uri, uri=True)
            try:
                row = db.execute("SELECT state_json FROM short_term_memory WHERE id=1").fetchone()
            finally:
                db.close()
            old = json.loads(row[0]) if row else {}
            texts = [str(old.get("overview") or "")]
            texts.extend(str(item.get("content") or "") for item in old.get("items", [])
                         if item.get("status") == "active" and item.get("category") in
                         {"active_context", "active_thread", "recent_topic"})
            return "\n".join(text for text in texts if text)[:1200]
        except (OSError, sqlite3.Error, ValueError, TypeError, AttributeError):
            return ""
