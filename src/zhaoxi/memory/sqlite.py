"""SQLite persistence for the local associative memory network."""

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

from zhaoxi.errors import MemoryError
from zhaoxi.memory.models import (
    MemoryCluster,
    MemoryEdge,
    MemoryEmbedding,
    MemoryEntity,
    MemoryQuery,
    MemoryRecord,
    MemorySearchResult,
    MemoryStatus,
)
from zhaoxi.memory.repository import MemoryRepository


SCHEMA_VERSION = 5
SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY, kind TEXT NOT NULL, shape TEXT NOT NULL DEFAULT 'node',
    content TEXT NOT NULL, normalized_content TEXT NOT NULL, summary TEXT,
    tags_json TEXT NOT NULL, entities_json TEXT NOT NULL DEFAULT '[]',
    participants_json TEXT NOT NULL DEFAULT '[]', source_type TEXT NOT NULL,
    source_ref TEXT, source TEXT, confidence REAL NOT NULL, importance REAL NOT NULL DEFAULT 0.6,
    relevance REAL NOT NULL DEFAULT 0.7, activation REAL NOT NULL DEFAULT 0.7,
    pinned INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, supersedes_id TEXT,
    cluster_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, event_at TEXT,
    recorded_at TEXT, known_at TEXT,
    valid_from TEXT, valid_until TEXT, last_confirmed_at TEXT, derived_at TEXT,
    accessed_at TEXT, access_count INTEGER NOT NULL DEFAULT 0, source_message_id TEXT,
    source_message_ids_json TEXT NOT NULL DEFAULT '[]', source_name TEXT,
    evidence_reference TEXT, evidence_memory_ids_json TEXT NOT NULL DEFAULT '[]',
    source_requeryable INTEGER NOT NULL DEFAULT 0, metadata_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_status_kind ON memories(status, kind);
CREATE INDEX IF NOT EXISTS idx_memories_updated ON memories(updated_at DESC);
CREATE TABLE IF NOT EXISTS memory_clusters (
    id TEXT PRIMARY KEY, topic TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '',
    importance REAL NOT NULL, activation REAL NOT NULL, time_start TEXT, time_end TEXT,
    member_count INTEGER NOT NULL DEFAULT 0, representative_memory_ids_json TEXT NOT NULL,
    tags_json TEXT NOT NULL, entities_json TEXT NOT NULL, metadata_json TEXT NOT NULL,
    centroid_embedding_json TEXT NOT NULL DEFAULT '[]', active INTEGER NOT NULL DEFAULT 1,
    merged_into_id TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memory_cluster_members (
    cluster_id TEXT NOT NULL, memory_id TEXT NOT NULL, membership_score REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(cluster_id, memory_id),
    FOREIGN KEY(cluster_id) REFERENCES memory_clusters(id) ON DELETE CASCADE,
    FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS memory_edges (
    id TEXT PRIMARY KEY, source_id TEXT NOT NULL, target_id TEXT NOT NULL, relation TEXT NOT NULL,
    relation_label TEXT, weight REAL NOT NULL, confidence REAL NOT NULL, activation REAL NOT NULL,
    valid_from TEXT, valid_until TEXT, evidence_json TEXT NOT NULL, created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, last_activated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_edges_source ON memory_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON memory_edges(target_id);
CREATE TABLE IF NOT EXISTS memory_embeddings (
    memory_id TEXT PRIMARY KEY, embedding_model TEXT NOT NULL, embedding_hash TEXT NOT NULL,
    vector_json TEXT NOT NULL, updated_at TEXT NOT NULL,
    FOREIGN KEY(memory_id) REFERENCES memories(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS memory_evidence (
    memory_id TEXT NOT NULL, evidence_memory_id TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(memory_id, evidence_memory_id)
);
CREATE TABLE IF NOT EXISTS memory_runtime (
    key TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memory_entities (
    id TEXT PRIMARY KEY, canonical_name TEXT NOT NULL, normalized_name TEXT NOT NULL UNIQUE,
    aliases_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""


class SQLiteMemoryRepository(MemoryRepository):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fts5_available = False
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
                    connection.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
                self._migrate_v4(connection)
                connection.execute("CREATE INDEX IF NOT EXISTS idx_memories_cluster ON memories(cluster_id)")
                try:
                    connection.execute(
                        "CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(memory_id UNINDEXED, content, summary)"
                    )
                    connection.execute("DELETE FROM memories_fts")
                    connection.execute(
                        "INSERT INTO memories_fts SELECT id, content, COALESCE(summary, '') FROM memories WHERE status='active'"
                    )
                    return True
                except sqlite3.OperationalError:
                    return False
        except sqlite3.Error as exc:
            raise MemoryError(f"无法初始化记忆数据库：{exc}") from exc

    async def create(self, record: MemoryRecord) -> MemoryRecord:
        return await asyncio.to_thread(self._write_record, record, False)

    async def save(self, record: MemoryRecord) -> MemoryRecord:
        return await asyncio.to_thread(self._write_record, record, True)

    def _write_record(self, record: MemoryRecord, replace: bool) -> MemoryRecord:
        values = self._record_values(record)
        columns = list(values)
        placeholders = ",".join("?" for _ in columns)
        if replace:
            updates = ",".join(f"{name}=excluded.{name}" for name in columns if name != "id")
            sql = f"INSERT INTO memories ({','.join(columns)}) VALUES ({placeholders}) ON CONFLICT(id) DO UPDATE SET {updates}"
        else:
            sql = f"INSERT INTO memories ({','.join(columns)}) VALUES ({placeholders})"
        try:
            with self._connect() as connection:
                connection.execute(sql, tuple(values.values()))
                self._sync_fts(connection, record)
                connection.execute("DELETE FROM memory_evidence WHERE memory_id=?", (record.id,))
                connection.executemany(
                    "INSERT OR IGNORE INTO memory_evidence(memory_id,evidence_memory_id) VALUES (?,?)",
                    [(record.id, item) for item in record.evidence_memory_ids],
                )
            return record
        except sqlite3.Error as exc:
            raise MemoryError(f"无法保存记忆：{exc}") from exc

    async def get(self, memory_id: str) -> MemoryRecord | None:
        return await asyncio.to_thread(self._get_sync, memory_id)

    def _get_sync(self, memory_id: str) -> MemoryRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        return self._from_row(row) if row else None

    async def find_by_normalized_content(self, content: str) -> MemoryRecord | None:
        return await asyncio.to_thread(self._find_normalized_sync, content)

    def _find_normalized_sync(self, content: str) -> MemoryRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE normalized_content=? ORDER BY updated_at DESC LIMIT 1", (content,)
            ).fetchone()
        return self._from_row(row) if row else None

    async def list_records(self, query: MemoryQuery) -> list[MemoryRecord]:
        return await asyncio.to_thread(self._list_records_sync, query)

    def _list_records_sync(self, query: MemoryQuery) -> list[MemoryRecord]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if query.statuses:
            clauses.append(f"status IN ({','.join('?' for _ in query.statuses)})")
            parameters.extend(item.value for item in query.statuses)
        if query.kind:
            clauses.append("kind=?")
            parameters.append(query.kind.value)
        if query.source_type:
            clauses.append("source_type=?")
            parameters.append(query.source_type.value)
        for tag in query.tags:
            clauses.append("tags_json LIKE ?")
            parameters.append(f'%\"{tag.strip().lower()}\"%')
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        candidate_limit = max(query.limit * 200, 10_000) if query.text else query.limit
        parameters.extend((candidate_limit, query.offset))
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM memories{where} ORDER BY updated_at DESC LIMIT ? OFFSET ?", parameters
            ).fetchall()
        return [self._from_row(row) for row in rows]

    async def search(self, query: MemoryQuery) -> list[MemorySearchResult]:
        records = await self.list_records(query)
        ranked = [self._rank(record, query.text) for record in records]
        if query.text:
            ranked = [item for item in ranked if item.text_score > 0]
            ranked.sort(key=lambda item: (item.score, item.record.updated_at), reverse=True)
        return ranked[: query.limit]

    @classmethod
    def _rank(cls, record: MemoryRecord, text: str) -> MemorySearchResult:
        if not text:
            return MemorySearchResult(record=record, score=record.confidence, match_reason="filter")
        query = text.casefold().strip()
        target = f"{record.content} {record.summary or ''} {' '.join(record.tags)} {' '.join(record.entities)}".casefold()
        if query in target:
            score, reason = 1.0, "exact substring"
        else:
            query_units, target_units = cls._search_units(query), cls._search_units(target)
            score = len(query_units & target_units) / max(len(query_units), 1)
            reason = "character/keyword overlap"
        return MemorySearchResult(
            record=record, score=round(score, 4), contextual_relevance=score,
            text_score=score, match_reason=reason,
        )

    @staticmethod
    def _search_units(value: str) -> set[str]:
        compact = "".join(character for character in value if character.isalnum())
        units = {token for token in value.split() if token}
        units.update(compact[index:index + 2] for index in range(max(len(compact) - 1, 0)))
        return units

    async def save_cluster(self, cluster: MemoryCluster) -> MemoryCluster:
        return await asyncio.to_thread(self._save_cluster_sync, cluster)

    def _save_cluster_sync(self, cluster: MemoryCluster) -> MemoryCluster:
        data = cluster.model_dump(mode="json")
        for key in ("representative_memory_ids", "tags", "entities", "metadata", "centroid_embedding"):
            data[f"{key}_json"] = json.dumps(data.pop(key), ensure_ascii=False)
        columns = list(data)
        sql = f"INSERT INTO memory_clusters ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) ON CONFLICT(id) DO UPDATE SET " + ",".join(f"{x}=excluded.{x}" for x in columns if x != "id")
        with self._connect() as connection:
            connection.execute(sql, tuple(data.values()))
        return cluster

    async def list_clusters(self) -> list[MemoryCluster]:
        return await asyncio.to_thread(self._list_clusters_sync)

    def _list_clusters_sync(self) -> list[MemoryCluster]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM memory_clusters ORDER BY updated_at DESC").fetchall()
        return [self._cluster_from_row(row) for row in rows]

    async def add_cluster_member(self, cluster_id: str, memory_id: str, score: float) -> None:
        await asyncio.to_thread(self._add_cluster_member_sync, cluster_id, memory_id, score)

    def _add_cluster_member_sync(self, cluster_id: str, memory_id: str, score: float) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO memory_cluster_members(cluster_id,memory_id,membership_score) VALUES (?,?,?)",
                (cluster_id, memory_id, score),
            )
            connection.execute("UPDATE memories SET cluster_id=? WHERE id=?", (cluster_id, memory_id))

    async def list_cluster_members(self, cluster_id: str) -> list[MemoryRecord]:
        return await asyncio.to_thread(self._list_cluster_members_sync, cluster_id)

    def _list_cluster_members_sync(self, cluster_id: str) -> list[MemoryRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT m.* FROM memories m JOIN memory_cluster_members cm ON cm.memory_id=m.id "
                "WHERE cm.cluster_id=? ORDER BY m.created_at", (cluster_id,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    async def merge_clusters(self, source_id: str, target_id: str) -> None:
        await asyncio.to_thread(self._merge_clusters_sync, source_id, target_id)

    def _merge_clusters_sync(self, source_id: str, target_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO memory_cluster_members(cluster_id,memory_id,membership_score,created_at) "
                "SELECT ?,memory_id,membership_score,created_at FROM memory_cluster_members WHERE cluster_id=?",
                (target_id, source_id),
            )
            connection.execute("UPDATE memories SET cluster_id=? WHERE cluster_id=?", (target_id, source_id))
            connection.execute("DELETE FROM memory_cluster_members WHERE cluster_id=?", (source_id,))
            connection.execute(
                "UPDATE memory_clusters SET active=0,merged_into_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (target_id, source_id),
            )

    async def save_edge(self, edge: MemoryEdge) -> MemoryEdge:
        return await asyncio.to_thread(self._save_edge_sync, edge)

    def _save_edge_sync(self, edge: MemoryEdge) -> MemoryEdge:
        data = edge.model_dump(mode="json")
        data["evidence_json"] = json.dumps(data.pop("evidence_memory_ids"), ensure_ascii=False)
        columns = list(data)
        sql = f"INSERT INTO memory_edges ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) ON CONFLICT(id) DO UPDATE SET " + ",".join(f"{x}=excluded.{x}" for x in columns if x != "id")
        with self._connect() as connection:
            connection.execute(sql, tuple(data.values()))
        return edge

    async def edges_for(self, node_ids: list[str], min_weight: float = 0) -> list[MemoryEdge]:
        if not node_ids:
            return []
        return await asyncio.to_thread(self._edges_for_sync, node_ids, min_weight)

    def _edges_for_sync(self, node_ids: list[str], min_weight: float) -> list[MemoryEdge]:
        marks = ",".join("?" for _ in node_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM memory_edges WHERE (source_id IN ({marks}) OR target_id IN ({marks})) AND weight>=?",
                [*node_ids, *node_ids, min_weight],
            ).fetchall()
        return [self._edge_from_row(row) for row in rows]

    async def save_embedding(self, embedding: MemoryEmbedding) -> MemoryEmbedding:
        return await asyncio.to_thread(self._save_embedding_sync, embedding)

    def _save_embedding_sync(self, embedding: MemoryEmbedding) -> MemoryEmbedding:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO memory_embeddings(memory_id,embedding_model,embedding_hash,vector_json,updated_at) VALUES (?,?,?,?,?) ON CONFLICT(memory_id) DO UPDATE SET embedding_model=excluded.embedding_model,embedding_hash=excluded.embedding_hash,vector_json=excluded.vector_json,updated_at=excluded.updated_at",
                (embedding.memory_id, embedding.embedding_model, embedding.embedding_hash,
                 json.dumps(embedding.vector), embedding.updated_at.isoformat()),
            )
        return embedding

    async def list_embeddings(self) -> list[MemoryEmbedding]:
        return await asyncio.to_thread(self._list_embeddings_sync)

    def _list_embeddings_sync(self) -> list[MemoryEmbedding]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM memory_embeddings").fetchall()
        return [MemoryEmbedding(memory_id=row["memory_id"], embedding_model=row["embedding_model"],
                                embedding_hash=row["embedding_hash"], vector=json.loads(row["vector_json"]),
                                updated_at=row["updated_at"]) for row in rows]

    async def diagnostics(self) -> dict[str, object]:
        return await asyncio.to_thread(self._diagnostics_sync)

    def _diagnostics_sync(self) -> dict[str, object]:
        with self._connect() as connection:
            total = connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            by_kind = dict(connection.execute("SELECT kind,COUNT(*) FROM memories GROUP BY kind").fetchall())
            by_status = dict(connection.execute("SELECT status,COUNT(*) FROM memories GROUP BY status").fetchall())
            clusters = connection.execute("SELECT COUNT(*) FROM memory_clusters").fetchone()[0]
            edges = connection.execute("SELECT COUNT(*) FROM memory_edges").fetchone()[0]
            unclustered = connection.execute("SELECT COUNT(*) FROM memories WHERE cluster_id IS NULL").fetchone()[0]
            embeddings = connection.execute("SELECT COUNT(*) FROM memory_embeddings").fetchone()[0]
            model_row = connection.execute("SELECT embedding_model FROM memory_embeddings LIMIT 1").fetchone()
            consolidated = connection.execute("SELECT value FROM memory_runtime WHERE key='last_consolidation_at'").fetchone()
            runtime = dict(connection.execute("SELECT key,value FROM memory_runtime").fetchall())
            edge_memories = connection.execute("SELECT COUNT(*) FROM memories WHERE shape='edge'").fetchone()[0]
            entity_nodes = connection.execute("SELECT COUNT(*) FROM memory_entities").fetchone()[0]
        return {"total": total, "by_kind": by_kind, "by_status": by_status, "clusters": clusters,
                "edges": edges, "unclustered": unclustered, "embedding_model": model_row[0] if model_row else None,
                "embedding_count": embeddings, "last_consolidation_at": consolidated[0] if consolidated else None,
                "auto_consolidation_enabled": runtime.get("auto_consolidation_enabled") == "true",
                "last_consolidation_check_at": runtime.get("last_consolidation_check_at"),
                "consolidation_checks": int(runtime.get("consolidation_checks", 0)),
                "consolidation_llm_calls": int(runtime.get("consolidation_llm_calls", 0)),
                "semantic_created": int(runtime.get("semantic_created", 0)),
                "semantic_updated": int(runtime.get("semantic_updated", 0)),
                "clusters_considered": int(runtime.get("clusters_considered", 0)),
                "cluster_merge_count": int(runtime.get("cluster_merge_count", 0)),
                "edge_memories": edge_memories, "graph_edges": edges, "entity_nodes": entity_nodes,
                "edge_extraction_success": int(runtime.get("edge_extraction_success", 0)),
                "edge_extraction_fallback": int(runtime.get("edge_extraction_fallback", 0))}

    async def set_runtime(self, key: str, value: str) -> None:
        await asyncio.to_thread(self._set_runtime_sync, key, value)

    def _set_runtime_sync(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO memory_runtime(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    async def get_runtime(self, key: str) -> str | None:
        return await asyncio.to_thread(self._get_runtime_sync, key)

    def _get_runtime_sync(self, key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM memory_runtime WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    async def save_entity(self, entity: MemoryEntity) -> MemoryEntity:
        return await asyncio.to_thread(self._save_entity_sync, entity)

    def _save_entity_sync(self, entity: MemoryEntity) -> MemoryEntity:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO memory_entities(id,canonical_name,normalized_name,aliases_json,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET canonical_name=excluded.canonical_name,"
                "normalized_name=excluded.normalized_name,aliases_json=excluded.aliases_json,updated_at=excluded.updated_at",
                (entity.id, entity.canonical_name, entity.normalized_name,
                 json.dumps(entity.aliases, ensure_ascii=False), entity.created_at.isoformat(), entity.updated_at.isoformat()),
            )
        return entity

    async def list_entities(self) -> list[MemoryEntity]:
        return await asyncio.to_thread(self._list_entities_sync)

    def _list_entities_sync(self) -> list[MemoryEntity]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM memory_entities ORDER BY created_at").fetchall()
        return [MemoryEntity(id=row["id"], canonical_name=row["canonical_name"], normalized_name=row["normalized_name"],
                             aliases=json.loads(row["aliases_json"]), created_at=row["created_at"],
                             updated_at=row["updated_at"]) for row in rows]

    def _sync_fts(self, connection: sqlite3.Connection, record: MemoryRecord) -> None:
        if not self.fts5_available:
            return
        connection.execute("DELETE FROM memories_fts WHERE memory_id=?", (record.id,))
        if record.status == MemoryStatus.ACTIVE:
            connection.execute("INSERT INTO memories_fts(memory_id,content,summary) VALUES (?,?,?)",
                               (record.id, record.content, record.summary or ""))

    @staticmethod
    def _record_values(record: MemoryRecord) -> dict[str, Any]:
        data = record.model_dump(mode="json")
        data["relevance"] = record.activation  # retained only for rollback compatibility
        for key in ("tags", "entities", "participants", "source_message_ids", "evidence_memory_ids", "metadata"):
            data[f"{key}_json"] = json.dumps(data.pop(key), ensure_ascii=False)
        return data

    @staticmethod
    def _from_row(row: sqlite3.Row) -> MemoryRecord:
        keys = set(row.keys())
        return MemoryRecord(
            id=row["id"], kind=row["kind"], shape=row["shape"] if "shape" in keys else "node",
            content=row["content"], normalized_content=row["normalized_content"], summary=row["summary"],
            tags=json.loads(row["tags_json"]), entities=json.loads(row["entities_json"]) if "entities_json" in keys else [],
            participants=json.loads(row["participants_json"]) if "participants_json" in keys else [],
            source_type=row["source_type"], source_ref=row["source_ref"], confidence=row["confidence"],
            source=(row["source"] if "source" in keys and row["source"] else row["source_name"] or row["source_type"]),
            importance=row["importance"], activation=row["activation"] if "activation" in keys else row["relevance"],
            pinned=bool(row["pinned"]), status=row["status"], supersedes_id=row["supersedes_id"],
            cluster_id=row["cluster_id"] if "cluster_id" in keys else None, created_at=row["created_at"],
            updated_at=row["updated_at"], event_at=row["event_at"] if "event_at" in keys else None,
            recorded_at=(row["recorded_at"] if "recorded_at" in keys and row["recorded_at"] else row["created_at"]),
            known_at=(row["known_at"] if "known_at" in keys and row["known_at"] else row["created_at"]),
            valid_from=row["valid_from"], valid_until=row["valid_until"],
            last_confirmed_at=row["last_confirmed_at"] if "last_confirmed_at" in keys else None,
            derived_at=row["derived_at"] if "derived_at" in keys else None, accessed_at=row["accessed_at"],
            access_count=row["access_count"], source_message_id=row["source_message_id"],
            source_message_ids=json.loads(row["source_message_ids_json"]) if "source_message_ids_json" in keys else [],
            source_name=row["source_name"], evidence_reference=row["evidence_reference"],
            evidence_memory_ids=json.loads(row["evidence_memory_ids_json"]) if "evidence_memory_ids_json" in keys else [],
            source_requeryable=bool(row["source_requeryable"]), metadata=json.loads(row["metadata_json"]),
        )

    @staticmethod
    def _cluster_from_row(row: sqlite3.Row) -> MemoryCluster:
        return MemoryCluster(id=row["id"], topic=row["topic"], summary=row["summary"], importance=row["importance"],
            activation=row["activation"], time_start=row["time_start"], time_end=row["time_end"], member_count=row["member_count"],
            representative_memory_ids=json.loads(row["representative_memory_ids_json"]), tags=json.loads(row["tags_json"]),
            entities=json.loads(row["entities_json"]), metadata=json.loads(row["metadata_json"]),
            centroid_embedding=json.loads(row["centroid_embedding_json"]) if "centroid_embedding_json" in row.keys() else [],
            active=bool(row["active"]) if "active" in row.keys() else True,
            merged_into_id=row["merged_into_id"] if "merged_into_id" in row.keys() else None,
            created_at=row["created_at"], updated_at=row["updated_at"])

    @staticmethod
    def _edge_from_row(row: sqlite3.Row) -> MemoryEdge:
        return MemoryEdge(id=row["id"], source_id=row["source_id"], target_id=row["target_id"], relation=row["relation"],
            relation_label=row["relation_label"], weight=row["weight"], confidence=row["confidence"], activation=row["activation"],
            valid_from=row["valid_from"], valid_until=row["valid_until"], evidence_memory_ids=json.loads(row["evidence_json"]),
            created_at=row["created_at"], updated_at=row["updated_at"], last_activated_at=row["last_activated_at"])

    @staticmethod
    def _migrate_v4(connection: sqlite3.Connection) -> None:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(memories)")}
        additions = {
            "importance": "REAL NOT NULL DEFAULT 0.6", "relevance": "REAL NOT NULL DEFAULT 0.7",
            "activation": "REAL NOT NULL DEFAULT 0.7", "shape": "TEXT NOT NULL DEFAULT 'node'",
            "pinned": "INTEGER NOT NULL DEFAULT 0", "access_count": "INTEGER NOT NULL DEFAULT 0",
            "source_message_id": "TEXT", "source_message_ids_json": "TEXT NOT NULL DEFAULT '[]'",
            "source_name": "TEXT", "evidence_reference": "TEXT", "evidence_memory_ids_json": "TEXT NOT NULL DEFAULT '[]'",
            "source_requeryable": "INTEGER NOT NULL DEFAULT 0", "entities_json": "TEXT NOT NULL DEFAULT '[]'",
            "participants_json": "TEXT NOT NULL DEFAULT '[]'", "cluster_id": "TEXT", "event_at": "TEXT",
            "recorded_at": "TEXT", "known_at": "TEXT", "source": "TEXT",
            "valid_from": "TEXT", "valid_until": "TEXT", "last_confirmed_at": "TEXT", "derived_at": "TEXT",
        }
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE memories ADD COLUMN {name} {definition}")
        if "relevance" in columns:
            connection.execute("UPDATE memories SET activation=relevance WHERE activation=0.7 AND relevance<>0.7")
        connection.execute("UPDATE memories SET recorded_at=created_at WHERE recorded_at IS NULL")
        connection.execute("UPDATE memories SET known_at=created_at WHERE known_at IS NULL")
        connection.execute("UPDATE memories SET source=COALESCE(source_name, source_type) WHERE source IS NULL")
        cluster_columns = {row["name"] for row in connection.execute("PRAGMA table_info(memory_clusters)")}
        for name, definition in {
            "centroid_embedding_json": "TEXT NOT NULL DEFAULT '[]'",
            "active": "INTEGER NOT NULL DEFAULT 1",
            "merged_into_id": "TEXT",
        }.items():
            if name not in cluster_columns:
                connection.execute(f"ALTER TABLE memory_clusters ADD COLUMN {name} {definition}")
        connection.execute("UPDATE schema_version SET version=?", (SCHEMA_VERSION,))
