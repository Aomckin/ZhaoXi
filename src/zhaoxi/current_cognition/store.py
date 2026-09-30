"""SQLite state store with a one-time, conservative v1 migration."""
from __future__ import annotations
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from .models import CognitionThread, CurrentCognitionState, EvidenceRef

class CurrentCognitionStore:
    def __init__(self, path: str | Path, *, legacy_stm_path: str | Path | None = None) -> None:
        self.path = Path(path)
        self.legacy_stm_path = Path(legacy_stm_path) if legacy_stm_path else None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS current_cognition (id INTEGER PRIMARY KEY CHECK(id=1), state_json TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS current_cognition_legacy_backup (id INTEGER PRIMARY KEY CHECK(id=1), state_json TEXT NOT NULL, migrated_at TEXT NOT NULL)")

    def load(self) -> CurrentCognitionState:
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT state_json FROM current_cognition WHERE id=1").fetchone()
            if not row:
                return CurrentCognitionState()
            raw = json.loads(row[0])
            if "overview" in raw and "threads" in raw:
                return CurrentCognitionState.model_validate(raw)
            # The old narrative is archived verbatim, never kept as a live patch target.
            now = datetime.now(ZoneInfo("Asia/Shanghai"))
            state = CurrentCognitionState(last_processed_message_id=raw.get("last_processed_message_id"))
            try:
                previous = datetime.fromisoformat(raw["updated_at"]) if raw.get("updated_at") else now
                if previous.tzinfo is None:
                    previous = previous.replace(tzinfo=now.tzinfo)
            except (TypeError, ValueError):
                previous = now
            fresh = (now - previous).total_seconds() < 7 * 86400
            candidate = re.sub(r"(?:该用户|用户自述|用户倾向|用户)", "暗苟", str(raw.get("narrative") or "")).strip()
            first = re.split(r"[。！？\n]", candidate)[0].strip()
            if fresh and first and len(first) <= 160 and not re.search(r"\d{1,2}:\d{2}|[\\/].*\.(?:db|py|md)|(?:早餐|午餐|晚餐)|(?:明天|后天|今晚|下周)", first):
                state.overview = first + "。"
            for index, text in enumerate((raw.get("ongoing_threads") or []) if fresh else []):
                text = re.sub(r"(?:该用户|用户)", "暗苟", str(text)).strip()
                if not text or len(text) > 120 or re.search(r"\d{1,2}:\d{2}|(?:早餐|午餐|晚餐)|(?:明天|后天|今晚|下周)", text):
                    continue
                key = "legacy_" + str(index + 1)
                state.threads.append(CognitionThread(key=key, title=text[:40], summary=text,
                    salience=0.5, first_seen_at=previous, last_updated_at=previous,
                    last_evidence_at=previous, source_refs=[EvidenceRef(source="legacy_migration", timestamp=previous)]))
                if len(state.threads) == 3:
                    break
            state.updated_at = now if state.overview or state.threads else None
            state.last_maintenance = {"decision": "MIGRATED", "reason": "conservative_v1_to_v2", "at": now.isoformat()}
            with db:
                db.execute("INSERT OR IGNORE INTO current_cognition_legacy_backup VALUES (1,?,?)", (row[0], now.isoformat()))
                db.execute("UPDATE current_cognition SET state_json=? WHERE id=1", (state.model_dump_json(),))
            return state

    def save(self, state: CurrentCognitionState) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO current_cognition(id,state_json) VALUES (1,?) ON CONFLICT(id) DO UPDATE SET state_json=excluded.state_json",
                       (state.model_dump_json(),))

    def legacy_reference(self) -> str:
        path = self.legacy_stm_path
        if path is None or not path.is_file():
            return ""
        try:
            db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
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
