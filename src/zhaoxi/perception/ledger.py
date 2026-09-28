"""Short-lived, shared record of verifiable Zhaoxi activity."""
import sqlite3
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from pydantic import BaseModel, Field


class SelfEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    event_type: str
    channel: str
    conversation_id: str | None = None
    actor_role: str | None = None
    actor_id: str | None = None
    summary: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_refs: list[str] = Field(default_factory=list)
    importance: float = 0.5
    private: bool = False
    expires_at: datetime | None = None


class InteractionLedger:
    def __init__(self, path: str | Path, ttl_hours: int = 48):
        self.path = Path(path)
        self.ttl_hours = ttl_hours
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS self_events (
                id TEXT PRIMARY KEY, occurred_at TEXT NOT NULL,
                expires_at TEXT NOT NULL, payload TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS runtime_self_state (
                id INTEGER PRIMARY KEY CHECK(id=1), updated_at TEXT NOT NULL,
                payload TEXT NOT NULL)""")

    def _connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def record(self, event_type: str, channel: str, summary: str, *,
               conversation_id: str | None = None, actor_role: str | None = None,
               actor_id: str | None = None, source_refs: list[str] | None = None,
               importance: float = 0.5, private: bool = False) -> SelfEvent:
        event = SelfEvent(event_type=event_type, channel=channel,
                          conversation_id=conversation_id, actor_role=actor_role,
                          actor_id=actor_id, summary=summary[:300],
                          source_refs=source_refs or [], importance=importance, private=private,
                          expires_at=datetime.now(UTC) + timedelta(hours=self.ttl_hours))
        with self._connect() as db:
            db.execute("INSERT INTO self_events VALUES (?,?,?,?)",
                       (event.event_id, event.occurred_at.isoformat(),
                        event.expires_at.isoformat(), event.model_dump_json()))
        return event

    def recent(self, limit: int = 8) -> list[SelfEvent]:
        with self._connect() as db:
            rows = db.execute("""SELECT payload FROM self_events WHERE expires_at > ?
                ORDER BY occurred_at DESC LIMIT ?""", (datetime.now(UTC).isoformat(), limit)).fetchall()
        return [SelfEvent.model_validate_json(row[0]) for row in rows]

    def context(self, limit: int = 8, max_chars: int = 1500,
                *, include_private: bool = True) -> str:
        events = self.recent(limit)
        if not events:
            return ""
        lines = []
        for item in reversed(events):
            summary = item.summary
            if item.private and not include_private:
                summary = ("已通过 QQ 私聊回复 Owner" if item.event_type == "external_reply_sent"
                           else "通过 QQ 私聊收到 Owner 消息")
            lines.append(f"{item.occurred_at.astimezone().strftime('%m-%d %H:%M')} {summary}")
        prefix = "[Interaction Ledger Debug]\n"
        suffix = "\n[/Interaction Ledger Debug]"
        body = "\n".join(lines)
        return prefix + body[-(max_chars - len(prefix) - len(suffix)):] + suffix

    def clear_expired(self) -> int:
        with self._connect() as db:
            result = db.execute("DELETE FROM self_events WHERE expires_at <= ?",
                                (datetime.now(UTC).isoformat(),))
        return result.rowcount


    def save_runtime_state(self, state: dict) -> None:
        with self._connect() as db:
            db.execute("""INSERT INTO runtime_self_state(id,updated_at,payload)
                VALUES (1,?,?) ON CONFLICT(id) DO UPDATE SET
                updated_at=excluded.updated_at,payload=excluded.payload""",
                (datetime.now(UTC).isoformat(), json.dumps(state, ensure_ascii=False, default=str)))

    def runtime_state(self) -> dict:
        with self._connect() as db:
            row = db.execute("SELECT updated_at,payload FROM runtime_self_state WHERE id=1").fetchone()
        if row is None:
            return {"perception": {"enabled": False}, "qq": {"connected": False}}
        state = json.loads(row[1])
        if datetime.now(UTC) - datetime.fromisoformat(row[0]) > timedelta(seconds=90):
            state.setdefault("qq", {})["connected"] = False
            state["qq"]["identity_verified"] = False
            state["qq"]["stale"] = True
        return state
