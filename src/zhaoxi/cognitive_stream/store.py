"""SQLite append-only event store with stable ordering and source deduplication."""
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from .models import CognitiveEvent, CognitiveEventType

class ExperienceStream:
    def __init__(self, path: str | Path = ".zhaoxi/experience.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, source TEXT NOT NULL,
                channel TEXT, session_id TEXT, actor_id TEXT, actor_role TEXT,
                occurred_at TEXT NOT NULL, received_at TEXT NOT NULL, payload TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS event_refs (
                source TEXT NOT NULL, source_ref TEXT NOT NULL, event_id TEXT NOT NULL,
                PRIMARY KEY(source, source_ref))""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(events)")}
            for field in ("turn_id", "reply_to_event_id", "caused_by_event_id"):
                if field not in columns:
                    db.execute(f"ALTER TABLE events ADD COLUMN {field} TEXT")
            if "turn_id" not in columns:
                self._backfill_causality(db)
            db.execute("""CREATE TABLE IF NOT EXISTS timeline_units (
                unit_id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            for field in ("session_id", "channel", "actor_id", "occurred_at", "turn_id", "reply_to_event_id", "caused_by_event_id"):
                db.execute(f"CREATE INDEX IF NOT EXISTS events_{field} ON events({field})")

    @staticmethod
    def _backfill_causality(db) -> None:
        """Infer causal columns for pre-v1.3.2 payloads once during schema migration."""
        rows = db.execute("SELECT event_id,payload FROM events ORDER BY rowid ASC").fetchall()
        known_turns: dict[str, str] = {}
        known_ids = {row[0] for row in rows}
        for event_id, payload in rows:
            event = CognitiveEvent.model_validate_json(payload)
            parent = next((ref for ref in event.parent_refs if ref in known_ids), None)
            turn_id = event.turn_id or (known_turns.get(parent, parent) if parent else event_id)
            reply_to = event.reply_to_event_id or (
                parent if event.event_type == CognitiveEventType.ASSISTANT_REPLY else None)
            cause = event.caused_by_event_id or (
                parent if parent and event.event_type != CognitiveEventType.ASSISTANT_REPLY else None)
            enriched = event.model_copy(update={"turn_id": turn_id,
                "reply_to_event_id": reply_to, "caused_by_event_id": cause})
            db.execute("""UPDATE events SET payload=?, turn_id=?, reply_to_event_id=?,
                        caused_by_event_id=? WHERE event_id=?""",
                       (enriched.model_dump_json(), turn_id, reply_to, cause, event_id))
            known_turns[event_id] = turn_id

    def _connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def append(self, event: CognitiveEvent) -> CognitiveEvent:
        with self._connect() as db:
            for ref in event.source_refs:
                row = db.execute("SELECT event_id FROM event_refs WHERE source=? AND source_ref=?",
                                 (event.source, ref)).fetchone()
                if row:
                    return self.get(row[0]) or event
            db.execute("""INSERT OR IGNORE INTO events
                (event_id,event_type,source,channel,session_id,actor_id,actor_role,
                 occurred_at,received_at,payload,turn_id,reply_to_event_id,caused_by_event_id)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (event.event_id, event.event_type.value, event.source, event.channel,
                        event.session_id, event.actor_id, event.actor_role,
                        event.occurred_at.isoformat(), event.received_at.isoformat(),
                        event.model_dump_json(), event.turn_id, event.reply_to_event_id,
                        event.caused_by_event_id))
            db.executemany("INSERT OR IGNORE INTO event_refs VALUES (?,?,?)",
                           [(event.source, ref, event.event_id) for ref in event.source_refs])
        return event

    def get(self, event_id: str) -> CognitiveEvent | None:
        with self._connect() as db:
            row = db.execute("SELECT payload FROM events WHERE event_id=?", (event_id,)).fetchone()
        return CognitiveEvent.model_validate_json(row[0]) if row else None

    def _query(self, where: str = "1=1", args: tuple = (), limit: int = 50) -> list[CognitiveEvent]:
        with self._connect() as db:
            rows = db.execute("SELECT payload FROM events WHERE " + where +
                              " ORDER BY occurred_at DESC, received_at DESC, event_id DESC LIMIT ?",
                              (*args, limit)).fetchall()
        return [CognitiveEvent.model_validate_json(row[0]) for row in rows]

    def recent(self, limit: int = 50) -> list[CognitiveEvent]:
        return self._query(limit=limit)

    def query_by_session(self, session_id: str, limit: int = 50) -> list[CognitiveEvent]:
        return self._query("session_id=?", (session_id,), limit)

    def query_by_channel(self, channel: str, limit: int = 50) -> list[CognitiveEvent]:
        return self._query("channel=?", (channel,), limit)

    def query_by_actor(self, actor_id: str, limit: int = 50) -> list[CognitiveEvent]:
        return self._query("actor_id=?", (actor_id,), limit)

    def query_since(self, time: datetime, limit: int = 200) -> list[CognitiveEvent]:
        return self._query("occurred_at>=?", (time.astimezone(UTC).isoformat(),), limit)

    def events_after(self, event_id: str | None, limit: int = 200) -> list[CognitiveEvent]:
        """Read ingestion order for maintenance cursors, independent of event time."""
        with self._connect() as db:
            marker = db.execute("SELECT rowid FROM events WHERE event_id=?", (event_id,)).fetchone() if event_id else None
            rows = db.execute("SELECT payload FROM events WHERE rowid>? ORDER BY rowid ASC LIMIT ?",
                              (marker[0] if marker else 0, limit)).fetchall()
        return [CognitiveEvent.model_validate_json(row[0]) for row in rows]

    def query_refs(self, source_refs: list[str], limit: int = 50) -> list[CognitiveEvent]:
        if not source_refs:
            return []
        marks = ",".join("?" for _ in source_refs)
        return self._query(f"event_id IN (SELECT event_id FROM event_refs WHERE source_ref IN ({marks}))",
                           tuple(source_refs), limit)

    def query_by_turn(self, turn_id: str, limit: int = 100) -> list[CognitiveEvent]:
        return self._query("turn_id=?", (turn_id,), limit)

    def recent_replies_in_session(self, session_id: str, since: datetime,
                                  limit: int = 30) -> list[CognitiveEvent]:
        return self._query("session_id=? AND event_type=? AND received_at>=?",
            (session_id, CognitiveEventType.ASSISTANT_REPLY.value,
             since.astimezone(UTC).isoformat()), limit)

    def query_by_reply_to(self, event_id: str, limit: int = 50) -> list[CognitiveEvent]:
        return self._query("reply_to_event_id=?", (event_id,), limit)

    def save_timeline_unit(self, unit_id: str, payload: str) -> None:
        with self._connect() as db:
            db.execute("INSERT OR REPLACE INTO timeline_units VALUES (?,?,?)",
                       (unit_id, payload, datetime.now(UTC).isoformat()))

    def resolve_timeline_unit(self, unit_id: str) -> dict | None:
        import json
        with self._connect() as db:
            row = db.execute("SELECT payload FROM timeline_units WHERE unit_id=?", (unit_id,)).fetchone()
        if not row:
            return None
        unit = json.loads(row[0])
        unit["events"] = [event.model_dump(mode="json") for event_id in unit.get("source_event_ids", [])
                          if (event := self.get(event_id)) is not None]
        return unit

    def stats(self) -> dict:
        with self._connect() as db:
            total = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            by_source = dict(db.execute("SELECT source, COUNT(*) FROM events GROUP BY source"))
            by_type = dict(db.execute("SELECT event_type, COUNT(*) FROM events GROUP BY event_type"))
        return {"total_events": total, "by_source": by_source, "by_type": by_type}

    def clear_expired(self, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        removed = 0
        with self._connect() as db:
            for event_id, payload in db.execute("SELECT event_id,payload FROM events").fetchall():
                event = CognitiveEvent.model_validate_json(payload)
                days = 7 if event.event_type.value.startswith("TOOL_") else (30 if event.actor_role != "OWNER" else 90)
                if event.received_at < now - timedelta(days=days):
                    db.execute("DELETE FROM event_refs WHERE event_id=?", (event_id,))
                    db.execute("DELETE FROM events WHERE event_id=?", (event_id,))
                    removed += 1
        return removed
