import json
import sqlite3
from datetime import timedelta

import pytest

from conftest import FakeProvider
from zhaoxi.cognitive.memory_decision import AutoMemory, MemoryAction
from zhaoxi.memory.models import (
    MemoryCandidate,
    MemoryCreate,
    MemoryEdge,
    MemoryKind,
    MemoryQuery,
    MemoryRelation,
    MemoryShape,
    MemoryStatus,
    utc_now,
)
from zhaoxi.memory.embedding import LocalHashEmbeddingProvider
from zhaoxi.memory.service import MemoryService
from zhaoxi.memory.sqlite import SQLiteMemoryRepository
from zhaoxi.models.types import ModelResponse


@pytest.mark.asyncio
async def test_atomic_batch_extracts_multiple_life_traces(tmp_path):
    payload = {
        "candidates": [
            {"kind": "episodic", "content": "今天中午吃了一碗粉。", "tags": ["饮食"]},
            {"kind": "episodic", "content": "今天下午去打了舞萌。", "tags": ["舞萌"]},
            {"kind": "intent", "content": "今晚准备继续修改朝汐。", "tags": ["开发"]},
        ]
    }
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    auto = AutoMemory(FakeProvider([ModelResponse(content=json.dumps(payload, ensure_ascii=False))]), service)
    decision = await auto.process("今天中午吃了碗粉，下午打了舞萌，晚上继续改朝汐。", "挺充实的一天。")
    assert decision.action == MemoryAction.CREATE
    assert decision.applied_count == 3
    records = await service.repository.list_records(MemoryQuery(statuses=[MemoryStatus.ACTIVE], limit=10))
    assert {record.kind for record in records} == {MemoryKind.EPISODIC, MemoryKind.INTENT}


def test_memory_candidate_supports_all_kinds_shape_and_time_fields():
    for kind in MemoryKind:
        candidate = MemoryCandidate(
            kind=kind, shape=MemoryShape.NODE, content=f"{kind.value} fact",
            event_at=utc_now(), valid_from=utc_now(), valid_until=utc_now() + timedelta(days=1),
            entities=["暗苟"], participants=["朝汐"], source_message_ids=["m1", "m2"],
        )
        assert candidate.kind == kind
        assert candidate.shape == MemoryShape.NODE


@pytest.mark.asyncio
async def test_drinking_cluster_and_normal_recall_diversity(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    for index in range(8):
        await service.remember(MemoryCreate(
            kind=MemoryKind.EPISODIC, content=f"第 {index} 次喝了啤酒。", tags=["生活"],
        ))
    for content, tag in (("今天继续开发朝汐记忆模块。", "开发"), ("下午投递了一份求职简历。", "求职")):
        await service.remember(MemoryCreate(kind=MemoryKind.EPISODIC, content=content, tags=[tag]))
    results = await service.search(MemoryQuery(text="啤酒 开发 求职", limit=8, per_cluster_limit=2))
    counts = {}
    for item in results:
        topic = item.cluster.topic if item.cluster else "none"
        counts[topic] = counts.get(topic, 0) + 1
    assert counts["饮酒"] <= 2
    assert "Zhaoxi开发" in counts
    assert "求职" in counts
    expanded = await service.search(MemoryQuery(text="我都喝过什么？", limit=8, per_cluster_limit=2))
    assert sum(item.cluster and item.cluster.topic == "饮酒" for item in expanded) > 2


@pytest.mark.asyncio
async def test_graph_expands_two_hops_without_looping(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    a = (await service.remember(MemoryCreate(kind="episodic", content="公寓结束准备返校。"))).record
    b = (await service.remember(MemoryCreate(kind="episodic", content="返校前继续开发朝汐。"))).record
    c = (await service.remember(MemoryCreate(kind="episodic", content="开发后整理了暑假歌单。"))).record
    await service.repository.save_edge(MemoryEdge(
        source_id=a.id, target_id=b.id, weight=0.9, relation_label="返校前后",
    ))
    await service.repository.save_edge(MemoryEdge(
        source_id=b.id, target_id=c.id, weight=0.9, relation_label="开发关联",
    ))
    results = await service.search(MemoryQuery(text="公寓结束", limit=5, max_hops=2))
    by_id = {item.record.id: item for item in results}
    assert by_id[b.id].graph_score > 0
    assert by_id[c.id].graph_score > 0
    assert by_id[b.id].seed_memory_id == a.id
    assert by_id[b.id].relation_label == "返校前后"
    assert by_id[b.id].graph_hop == 1
    assert by_id[c.id].graph_hop == 2
    assert any("path=seed:" in reason for reason in by_id[c.id].why_selected)
    assert len(by_id) == 3


@pytest.mark.asyncio
async def test_consolidation_preserves_episodes_and_builds_evidence_graph(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    episodes = []
    for content in ("周一深夜写代码效率很高。", "周三晚上开发很专注。", "周末夜里顺利完成开发。"):
        episodes.append((await service.remember(MemoryCreate(kind="episodic", content=content, tags=["开发"]))).record)
    semantic = await service.consolidate(
        [item.id for item in episodes], "用户通常在夜间更容易进入高专注开发状态。", tags=["开发规律"]
    )
    assert semantic.evidence_memory_ids == [item.id for item in episodes]
    assert semantic.derived_at is not None
    statuses = [(await service.require(item.id)).status for item in episodes]
    assert statuses == [MemoryStatus.ACTIVE] * 3
    edges = await service.repository.edges_for([semantic.id], 0)
    assert {edge.relation for edge in edges} >= {MemoryRelation.EVIDENCE_FOR, MemoryRelation.DERIVED_FROM}


@pytest.mark.asyncio
async def test_expired_state_is_time_penalized_and_diagnostics_are_content_free(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    now = utc_now()
    expired = (await service.remember(MemoryCreate(
        kind="state", content="目前住在学校。", valid_until=now - timedelta(days=30),
    ))).record
    current = (await service.remember(MemoryCreate(
        kind="state", content="目前住在公寓。", valid_from=now - timedelta(days=1),
        supersedes_id=expired.id,
    ))).record
    results = await service.search(MemoryQuery(
        text="目前住在哪里", limit=5, now=now,
        statuses=[MemoryStatus.ACTIVE, MemoryStatus.SUPERSEDED],
    ))
    scores = {item.record.id: item.time_score for item in results}
    assert scores[current.id] > scores[expired.id]
    diagnostics = await service.diagnostics()
    assert diagnostics["total"] == 2
    assert diagnostics["embedding_count"] == 2
    assert "住在" not in repr(diagnostics)


def test_v2_relevance_is_migrated_to_activation(tmp_path):
    path = tmp_path / "memory.db"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
        CREATE TABLE schema_version (version INTEGER NOT NULL);
        INSERT INTO schema_version VALUES (2);
        CREATE TABLE memories (
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, content TEXT NOT NULL, normalized_content TEXT NOT NULL,
          summary TEXT, tags_json TEXT NOT NULL, source_type TEXT NOT NULL, source_ref TEXT, confidence REAL NOT NULL,
          importance REAL NOT NULL, relevance REAL NOT NULL, pinned INTEGER NOT NULL, status TEXT NOT NULL,
          supersedes_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, accessed_at TEXT,
          access_count INTEGER NOT NULL, source_message_id TEXT, source_name TEXT, evidence_reference TEXT,
          source_requeryable INTEGER NOT NULL, valid_from TEXT, valid_until TEXT, metadata_json TEXT NOT NULL
        );
        INSERT INTO memories VALUES ('old','semantic','旧事实','旧事实',NULL,'[]','user',NULL,1,0.8,0.42,0,
          'active',NULL,'2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00',NULL,0,NULL,NULL,NULL,0,NULL,NULL,'{}');
        """)
    repository = SQLiteMemoryRepository(path)
    record = __import__("asyncio").run(repository.get("old"))
    assert record.activation == pytest.approx(0.42)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version FROM schema_version").fetchone()[0] == 5


@pytest.mark.asyncio
async def test_ten_thousand_memory_linear_keyword_and_embedding_scan(tmp_path):
    path = tmp_path / "memory.db"
    repository = SQLiteMemoryRepository(path)
    provider = LocalHashEmbeddingProvider(dimensions=8)
    now = utc_now().isoformat()
    query_text = "夜间高效编码规律"
    query_vector = await provider.embed(query_text)
    memories = []
    embeddings = []
    for index in range(10_000):
        memory_id = f"bulk-{index}"
        content = "语义目标" if index == 7_777 else f"普通生活记录 marker-{index}"
        memories.append((memory_id, "episodic", content, content, "[]", "user", 1.0,
                         "active", now, now, "{}"))
        vector = query_vector if index == 7_777 else [0.0] * 8
        embeddings.append((memory_id, provider.model, f"hash-{index}", json.dumps(vector), now))
    with sqlite3.connect(path) as connection:
        connection.executemany(
            "INSERT INTO memories(id,kind,content,normalized_content,tags_json,source_type,confidence,status,created_at,updated_at,metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            memories,
        )
        connection.executemany(
            "INSERT INTO memory_embeddings(memory_id,embedding_model,embedding_hash,vector_json,updated_at) VALUES (?,?,?,?,?)",
            embeddings,
        )
    service = MemoryService(repository, embedding_provider=provider)
    semantic = await service.search(MemoryQuery(text=query_text, limit=3))
    assert semantic[0].record.id == "bulk-7777"
    keyword = await service.search(MemoryQuery(text="marker-9999", limit=3))
    assert keyword[0].record.id == "bulk-9999"
