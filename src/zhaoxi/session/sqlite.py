"""Privacy-bounded SQLite storage for short-term sessions."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from zhaoxi.core.conversation import Conversation
from zhaoxi.core.message import Message, Role
from zhaoxi.session.base import Session, SessionStore


SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    max_messages INTEGER NOT NULL,
    messages_json TEXT NOT NULL
);
"""


class SQLiteSessionStore(SessionStore):
    """Persist only user/assistant text; Tool payloads and metadata are excluded."""

    def __init__(self, path: str | Path, *, max_messages: int = 40) -> None:
        self.path = Path(path)
        self.max_messages = max_messages
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
            row = connection.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            if row is None:
                connection.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
            elif row["version"] > SCHEMA_VERSION:
                raise RuntimeError("Session 数据库版本高于当前程序支持版本。")

    async def create(self) -> Session:
        session = Session(conversation=Conversation(max_messages=self.max_messages))
        await self.save(session)
        return session

    async def get(self, session_id: str) -> Session | None:
        return await asyncio.to_thread(self._get, session_id)

    def get_sync(self, session_id: str) -> Session | None:
        return self._get(session_id)

    def _get(self, session_id: str) -> Session | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()
        if row is None:
            return None
        messages = [Message.model_validate(item) for item in json.loads(row["messages_json"])]
        return Session(
            id=row["session_id"],
            conversation=Conversation(messages, max_messages=row["max_messages"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    async def save(self, session: Session) -> None:
        await asyncio.to_thread(self.save_sync, session)

    def save_sync(self, session: Session) -> None:
        session.updated_at = datetime.now(UTC)
        safe_messages = [
            message.model_dump(mode="json", exclude={"metadata", "tool_calls", "tool_call_id", "name"})
            for message in session.conversation.recent(self.max_messages)
            if message.role in {Role.USER, Role.ASSISTANT} and message.content is not None
        ]
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO sessions(session_id, created_at, updated_at, max_messages, messages_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET updated_at=excluded.updated_at,
                max_messages=excluded.max_messages, messages_json=excluded.messages_json""",
                (
                    session.id,
                    session.created_at.isoformat(),
                    session.updated_at.isoformat(),
                    self.max_messages,
                    json.dumps(safe_messages, ensure_ascii=False, separators=(",", ":")),
                ),
            )

    async def delete(self, session_id: str) -> bool:
        return await asyncio.to_thread(self._delete, session_id)

    def _delete(self, session_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
        return cursor.rowcount > 0

    async def list(self) -> list[Session]:
        with self._connect() as connection:
            ids = [row["session_id"] for row in connection.execute(
                "SELECT session_id FROM sessions ORDER BY updated_at DESC"
            ).fetchall()]
        sessions = [await self.get(session_id) for session_id in ids]
        return [session for session in sessions if session is not None]
