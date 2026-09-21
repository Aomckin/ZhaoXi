"""Privacy-bounded SQLite storage for short-term sessions."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path

from zhaoxi.core.conversation import Conversation
from zhaoxi.core.message import (
    Message,
    Role,
    assistant_persistence_violations,
    strip_echoed_timeline_header,
)
from zhaoxi.session.base import Session, SessionStore


SCHEMA_VERSION = 2
logger = logging.getLogger("SESSION")
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
    """Persist user/assistant text and image attachments; Tool payloads and metadata are excluded."""

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
            if row is not None and row["version"] < 2:
                self._migrate_timeline_headers(connection)
                connection.execute("UPDATE schema_version SET version=?", (SCHEMA_VERSION,))

    @staticmethod
    def _clean_serialized_messages(value: str) -> tuple[str, bool]:
        messages = json.loads(value)
        changed = False
        for item in messages:
            content = item.get("content")
            if item.get("role") == Role.ASSISTANT.value and isinstance(content, str):
                clean = strip_echoed_timeline_header(content)
                if clean != content:
                    item["content"] = clean
                    changed = True
                if item.get("background"):
                    item["background"] = ""
                    changed = True
        return json.dumps(messages, ensure_ascii=False, separators=(",", ":")), changed

    @classmethod
    def _migrate_timeline_headers(cls, connection: sqlite3.Connection) -> None:
        """Remove exact leaked internal headers from all stored assistant replies."""
        rows = connection.execute("SELECT session_id, messages_json FROM sessions").fetchall()
        for row in rows:
            try:
                cleaned, changed = cls._clean_serialized_messages(row["messages_json"])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if changed:
                connection.execute(
                    "UPDATE sessions SET messages_json=? WHERE session_id=?",
                    (cleaned, row["session_id"]),
                )

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
        serialized, changed = self._clean_serialized_messages(row["messages_json"])
        if changed:
            with self._connect() as connection:
                connection.execute(
                    "UPDATE sessions SET messages_json=? WHERE session_id=?",
                    (serialized, session_id),
                )
        messages = [Message.model_validate(item) for item in json.loads(serialized)]
        for message in messages:
            # v1.1.1 stored activation context inside the assistant body.
            prefix = "[朝汐主动消息 · "
            if message.role == Role.ASSISTANT and not message.delivery_id and (message.content or '').startswith(prefix):
                header, separator, body = message.content.partition(']\n')
                if separator:
                    try:
                        original_time = datetime.fromisoformat(header[len(prefix):])
                    except ValueError:
                        continue
                    if original_time.tzinfo is None:
                        continue
                    content, _, background = body.partition('\n相关背景：')
                    message.delivery_id = 'legacy-' + hashlib.sha256(message.content.encode()).hexdigest()
                    message.timestamp, message.content, message.background = original_time, content, background[:2000]
            if message.role == Role.ASSISTANT and not message.delivery_id and message.content:
                message.content = strip_echoed_timeline_header(message.content)
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
        safe_messages = []
        for message in session.conversation.recent(self.max_messages):
            if message.role not in {Role.USER, Role.ASSISTANT} or message.content is None:
                continue
            content = message.content
            if message.role == Role.ASSISTANT:
                violations = assistant_persistence_violations(content)
                if violations:
                    logger.warning(
                        "assistant persistence contamination preserved message_id=%s markers=%s",
                        message.message_id,
                        violations,
                    )
                content = strip_echoed_timeline_header(content)
            safe_messages.append(
                message.model_copy(update={"content": content, "background": ""}).model_dump(
                    mode="json",
                    exclude={"metadata", "tool_calls", "tool_call_id", "name", "background"},
                )
            )
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO sessions(session_id, created_at, updated_at, max_messages, messages_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET created_at=excluded.created_at, updated_at=excluded.updated_at,
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
