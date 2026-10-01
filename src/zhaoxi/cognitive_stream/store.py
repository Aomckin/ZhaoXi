"""SQLite append-only event store with stable ordering and source deduplication."""
import sqlite3
from zhaoxi.reliability.sqlite import connect
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zhaoxi.reliability.media import MediaBlobStore
from .models import CognitiveEvent, CognitiveEventType

class ExperienceStream:
    def __init__(self, path: str | Path = ".zhaoxi/experience.db", *, media_directory=None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.media=MediaBlobStore(media_directory or self.path.parent / "media")
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

    def _backfill_causality(self, db) -> None:
        """Infer causal columns for pre-v1.3.2 payloads once during schema migration."""
        rows = db.execute("SELECT event_id,payload FROM events ORDER BY rowid ASC").fetchall()
        known_turns: dict[str, str] = {}
        known_ids = {row[0] for row in rows}
        for event_id, payload in rows:
            event = CognitiveEvent.model_validate(self.media.loads(payload))
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
                       (self.media.dumps(enriched.model_dump(mode="json")), turn_id, reply_to, cause, event_id))
            known_turns[event_id] = turn_id

    def _connect(self):
        return connect(self.path, timeout=10)

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
                        self.media.dumps(event.model_dump(mode="json")), event.turn_id, event.reply_to_event_id,
                        event.caused_by_event_id))
            db.executemany("INSERT OR IGNORE INTO event_refs VALUES (?,?,?)",
                           [(event.source, ref, event.event_id) for ref in event.source_refs])
        return event

    def get(self, event_id: str) -> CognitiveEvent | None:
        with self._connect() as db:
            row = db.execute("SELECT payload FROM events WHERE event_id=?", (event_id,)).fetchone()
        return CognitiveEvent.model_validate(self.media.loads(row[0])) if row else None

    def _query(self, where: str = "1=1", args: tuple = (), limit: int = 50) -> list[CognitiveEvent]:
        with self._connect() as db:
            rows = db.execute("SELECT payload FROM events WHERE " + where +
                              " ORDER BY occurred_at DESC, received_at DESC, event_id DESC LIMIT ?",
                              (*args, limit)).fetchall()
        return [CognitiveEvent.model_validate(self.media.loads(row[0])) for row in rows]

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
        return [CognitiveEvent.model_validate(self.media.loads(row[0])) for row in rows]

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

    def load_timeline_unit(self, unit_id):
        import json
        with self._connect() as db:
            row = db.execute("SELECT payload FROM timeline_units WHERE unit_id=?",(unit_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def resolve_timeline_unit(self, unit_id: str) -> dict | None:
        unit = self.load_timeline_unit(unit_id)
        if unit is None:
            return None
        unit["events"] = [event.model_dump(mode="json") for event_id in unit.get("source_event_ids", [])
                          if (event := self.get(event_id)) is not None]
        from .social_trace import SocialTraceReader
        unit["social_trace"] = SocialTraceReader(self).read(unit_id)
        unit["missing_event_ids"] = [ref for ref in unit.get("source_event_ids",[]) if self.get(ref) is None]
        return unit

    def stats(self) -> dict:
        with self._connect() as db:
            total = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            by_source = dict(db.execute("SELECT source, COUNT(*) FROM events GROUP BY source"))
            by_type = dict(db.execute("SELECT event_type, COUNT(*) FROM events GROUP BY event_type"))
        return {"total_events": total, "by_source": by_source, "by_type": by_type}

    def retained_social_refs(self):
        import json
        with self._connect() as db:
            rows=db.execute("SELECT payload FROM events WHERE event_type=?",(CognitiveEventType.SOCIAL_SNAPSHOT.value,)).fetchall()
        return {ref for row in rows for ref in [*json.loads(row[0]).get("parent_refs",[]),*json.loads(row[0]).get("source_refs",[])]}

    def clear_expired(self, now: datetime | None = None) -> int:
        import json
        now = now or datetime.now(UTC)
        removed = 0
        with self._connect() as db:
            rows=db.execute("SELECT event_id,event_type,actor_role,received_at,payload,source FROM events").fetchall()
            expired=set()
            summaries={}
            for event_id,event_type,actor_role,received_at,payload,source in rows:
                received=datetime.fromisoformat(received_at)
                if received.tzinfo is None:received=received.replace(tzinfo=UTC)
                days=7 if event_type.startswith("TOOL_") else (30 if actor_role!="OWNER" else 90)
                if received < now-timedelta(days=days):expired.add(event_id)
                if event_type==CognitiveEventType.SOCIAL_SNAPSHOT.value:
                    summaries[event_id]=(source,json.loads(payload).get("parent_refs",[]))
            # A live summary or cached unit owns its evidence lifetime. Cache units
            # expire after 30 days; repeated reads do not refresh their timestamp.
            db.execute("DELETE FROM timeline_units WHERE updated_at<?",((now-timedelta(days=30)).isoformat(),))
            protected={ref for payload, in db.execute("SELECT payload FROM timeline_units") for ref in json.loads(payload).get("source_event_ids",[])}
            pending=list(set(summaries)-expired | (protected & set(summaries)))
            visited=set()
            while pending:
                summary=pending.pop()
                if summary in visited:continue
                visited.add(summary)
                source,refs=summaries[summary]
                for ref in refs:
                    row=db.execute("SELECT event_id FROM event_refs WHERE source=? AND source_ref=?",(source,ref)).fetchone()
                    child=row[0] if row else ref
                    protected.add(child)
                    if child in summaries:pending.append(child)
            for event_id in expired-protected:
                db.execute("DELETE FROM event_refs WHERE event_id=?",(event_id,))
                db.execute("DELETE FROM events WHERE event_id=?",(event_id,))
                removed+=1
        return removed
