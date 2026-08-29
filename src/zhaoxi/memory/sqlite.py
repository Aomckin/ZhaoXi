"""SQLite persistence for local long-term memory."""

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

from zhaoxi.errors import MemoryError
from zhaoxi.memory.models import (
    MemoryQuery,
    MemoryRecord,
    MemorySearchResult,
    MemoryStatus,
    utc_now,
)
from zhaoxi.memory.repository import MemoryRepository


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    normalized_content TEXT NOT NULL,
    summary TEXT,
    tags_json TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_ref TEXT,
    confidence REAL NOT NULL,
    status TEXT NOT NULL,
    supersedes_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    accessed_at TEXT,
    metadata_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_status_kind ON memories(status, kind);
CREATE INDEX IF NOT EXISTS idx_memories_normalized ON memories(normalized_content);
CREATE INDEX IF NOT EXISTS idx_memories_updated ON memories(updated_at DESC);
"""


class SQLiteMemoryRepository(MemoryRepository):
    """Open short-lived SQLite connections so async callers remain thread-safe."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fts5_available = self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> bool:
        try:
            with self._connect() as connection:
                connection.executescript(SCHEMA)
                row = connection.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
                if row is None:
                    connection.execute("INSERT INTO schema_version(version) VALUES (1)")
                try:
                    connection.execute(
                        "CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(memory_id UNINDEXED, content, summary)"
                    )
                    return True
                except sqlite3.OperationalError:
                    return False
        except sqlite3.Error as exc:
            raise MemoryError(f"无法初始化记忆数据库：{exc}") from exc

    async def create(self, record: MemoryRecord) -> MemoryRecord:
        return await asyncio.to_thread(self._create_sync, record)

    def _create_sync(self, record: MemoryRecord) -> MemoryRecord:
        try:
            with self._connect() as connection:
                connection.execute(
                    """INSERT INTO memories (
                    id, kind, content, normalized_content, summary, tags_json,
                    source_type, source_ref, confidence, status, supersedes_id,
                    created_at, updated_at, accessed_at, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    self._values(record),
                )
                self._sync_fts(connection, record)
            return record
        except sqlite3.Error as exc:
            raise MemoryError(f"无法保存记忆：{exc}") from exc

    async def get(self, memory_id: str) -> MemoryRecord | None:
        return await asyncio.to_thread(self._get_sync, memory_id)

    def _get_sync(self, memory_id: str) -> MemoryRecord | None:
        try:
            with self._connect() as connection:
                row = connection.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
            return self._from_row(row) if row else None
        except sqlite3.Error as exc:
            raise MemoryError(f"无法读取记忆：{exc}") from exc

    async def save(self, record: MemoryRecord) -> MemoryRecord:
        return await asyncio.to_thread(self._save_sync, record)

    def _save_sync(self, record: MemoryRecord) -> MemoryRecord:
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    """UPDATE memories SET
                    kind=?, content=?, normalized_content=?, summary=?, tags_json=?,
                    source_type=?, source_ref=?, confidence=?, status=?, supersedes_id=?,
                    created_at=?, updated_at=?, accessed_at=?, metadata_json=? WHERE id=?""",
                    (*self._values(record)[1:], record.id),
                )
                if cursor.rowcount == 0:
                    raise MemoryError(f"记忆不存在：{record.id}")
                self._sync_fts(connection, record)
            return record
        except MemoryError:
            raise
        except sqlite3.Error as exc:
            raise MemoryError(f"无法更新记忆：{exc}") from exc

    async def find_by_normalized_content(self, content: str) -> MemoryRecord | None:
        return await asyncio.to_thread(self._find_normalized_sync, content)

    def _find_normalized_sync(self, content: str) -> MemoryRecord | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT * FROM memories WHERE normalized_content=? ORDER BY updated_at DESC LIMIT 1",
                    (content,),
                ).fetchone()
            return self._from_row(row) if row else None
        except sqlite3.Error as exc:
            raise MemoryError(f"无法检查重复记忆：{exc}") from exc

    async def search(self, query: MemoryQuery) -> list[MemorySearchResult]:
        return await asyncio.to_thread(self._search_sync, query)

    def _search_sync(self, query: MemoryQuery) -> list[MemorySearchResult]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if query.statuses:
            placeholders = ",".join("?" for _ in query.statuses)
            clauses.append(f"status IN ({placeholders})")
            parameters.extend(item.value for item in query.statuses)
        if query.kind:
            clauses.append("kind=?")
            parameters.append(query.kind.value)
        if query.source_type:
            clauses.append("source_type=?")
            parameters.append(query.source_type.value)
        for tag in query.tags:
            clauses.append("tags_json LIKE ?")
            parameters.append(f'%"{tag.strip().lower()}"%')
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        candidate_limit = max(query.limit * 20, 100) if query.text else query.limit
        sql = f"SELECT * FROM memories{where} ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        parameters.extend((candidate_limit, query.offset))
        try:
            with self._connect() as connection:
                rows = connection.execute(sql, parameters).fetchall()
                records = [self._from_row(row) for row in rows]
                ranked = [self._rank(record, query.text) for record in records]
                if query.text:
                    ranked = [item for item in ranked if item.score > item.record.confidence * 0.2]
                    ranked.sort(key=lambda item: (item.score, item.record.updated_at), reverse=True)
                ranked = ranked[: query.limit]
                now = utc_now().isoformat()
                if ranked:
                    connection.executemany(
                        "UPDATE memories SET accessed_at=? WHERE id=?",
                        [(now, item.record.id) for item in ranked],
                    )
            return ranked
        except sqlite3.Error as exc:
            raise MemoryError(f"无法搜索记忆：{exc}") from exc

    @staticmethod
    def _rank(record: MemoryRecord, text: str) -> MemorySearchResult:
        if not text:
            return MemorySearchResult(record=record, score=record.confidence, match_reason="filter")
        query = text.casefold().strip()
        target = f"{record.content} {record.summary or ''} {' '.join(record.tags)}".casefold()
        if query in target:
            relevance = 1.0
            reason = "exact substring"
        else:
            query_units = SQLiteMemoryRepository._search_units(query)
            target_units = SQLiteMemoryRepository._search_units(target)
            relevance = len(query_units & target_units) / max(len(query_units), 1)
            reason = "character/keyword overlap"
        return MemorySearchResult(
            record=record,
            score=round(relevance * 0.8 + record.confidence * 0.2, 4),
            match_reason=reason,
        )

    @staticmethod
    def _search_units(value: str) -> set[str]:
        compact = "".join(character for character in value if character.isalnum())
        units = {token for token in value.split() if token}
        units.update(compact[index : index + 2] for index in range(max(len(compact) - 1, 0)))
        return units

    def _sync_fts(self, connection: sqlite3.Connection, record: MemoryRecord) -> None:
        if not self.fts5_available:
            return
        connection.execute("DELETE FROM memories_fts WHERE memory_id=?", (record.id,))
        if record.status == MemoryStatus.ACTIVE:
            connection.execute(
                "INSERT INTO memories_fts(memory_id, content, summary) VALUES (?, ?, ?)",
                (record.id, record.content, record.summary or ""),
            )

    @staticmethod
    def _values(record: MemoryRecord) -> tuple[Any, ...]:
        return (
            record.id,
            record.kind.value,
            record.content,
            record.normalized_content,
            record.summary,
            json.dumps(record.tags, ensure_ascii=False),
            record.source_type.value,
            record.source_ref,
            record.confidence,
            record.status.value,
            record.supersedes_id,
            record.created_at.isoformat(),
            record.updated_at.isoformat(),
            record.accessed_at.isoformat() if record.accessed_at else None,
            json.dumps(record.metadata, ensure_ascii=False),
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            id=row["id"],
            kind=row["kind"],
            content=row["content"],
            normalized_content=row["normalized_content"],
            summary=row["summary"],
            tags=json.loads(row["tags_json"]),
            source_type=row["source_type"],
            source_ref=row["source_ref"],
            confidence=row["confidence"],
            status=row["status"],
            supersedes_id=row["supersedes_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            accessed_at=row["accessed_at"],
            metadata=json.loads(row["metadata_json"]),
        )
