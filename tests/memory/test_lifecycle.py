import sqlite3
from datetime import timedelta

import pytest

from conftest import FakeProvider
from zhaoxi.cognitive.memory_decision import AutoMemory, MemoryAction, MemoryDecision
from zhaoxi.memory.lifecycle import MemoryLifecyclePolicy
from zhaoxi.memory.models import (
    MemoryCreate,
    MemoryKind,
    MemoryQuery,
    MemoryStatus,
    utc_now,
)
from zhaoxi.memory.service import MemoryService
from zhaoxi.memory.sqlite import SQLiteMemoryRepository
from zhaoxi.models.types import ModelResponse


async def create_memory(service, content, *, importance, relevance, pinned=False):
    return (await service.remember(MemoryCreate(
        content=content,
        importance=importance,
        relevance=relevance,
        pinned=pinned,
    ))).record


@pytest.mark.asyncio
async def test_high_importance_memory_becomes_cold_but_is_not_forgotten(tmp_path):
    policy = MemoryLifecyclePolicy(relevance_decay_per_day=0.02)
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"), policy)
    record = await create_memory(
        service, "项目名拼音必须写 Zhaoxi", importance=0.95, relevance=0.8
    )
    record.created_at = utc_now() - timedelta(days=100)
    record.updated_at = record.created_at
    await service.repository.save(record)
    await service.maintain()
    maintained = await service.require(record.id)
    assert maintained.importance == 0.95
    assert maintained.relevance == 0
    assert maintained.status == MemoryStatus.COLD


@pytest.mark.asyncio
async def test_low_importance_memory_moves_from_active_to_cold_then_archived(tmp_path):
    policy = MemoryLifecyclePolicy(relevance_decay_per_day=0.02)
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"), policy)
    record = await create_memory(
        service, "最近正在调整一个按钮布局", importance=0.2, relevance=0.8
    )
    record.created_at = utc_now() - timedelta(days=100)
    record.updated_at = record.created_at
    await service.repository.save(record)
    await service.maintain()
    assert (await service.require(record.id)).status == MemoryStatus.COLD
    record = await service.require(record.id)
    record.updated_at = utc_now() - timedelta(days=31)
    await service.repository.save(record)
    await service.maintain()
    assert (await service.require(record.id)).status == MemoryStatus.ARCHIVED


@pytest.mark.asyncio
async def test_cold_memory_search_reactivates_and_boosts_relevance(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    record = await create_memory(
        service, "用户晚上更喜欢开发项目", importance=0.8, relevance=0.1
    )
    record.status = MemoryStatus.COLD
    await service.repository.save(record)
    results = await service.search(MemoryQuery(text="晚上开发", limit=5))
    activated = await service.require(record.id)
    assert [item.record.id for item in results] == [record.id]
    assert activated.status == MemoryStatus.ACTIVE
    assert activated.relevance > 0.1
    assert activated.access_count == 1


@pytest.mark.asyncio
async def test_explicit_history_search_returns_cold_without_reactivating(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    record = await create_memory(service, "旧项目的命名讨论", importance=0.5, relevance=0.1)
    record.status = MemoryStatus.COLD
    await service.repository.save(record)
    results = await service.search(MemoryQuery(
        text="命名讨论", statuses=[MemoryStatus.COLD], limit=5
    ))
    assert [item.record.id for item in results] == [record.id]
    unchanged = await service.require(record.id)
    assert unchanged.status == MemoryStatus.COLD
    assert unchanged.access_count == 0


@pytest.mark.asyncio
async def test_pinned_memory_is_never_archived_but_user_can_forget_it(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    record = await create_memory(
        service, "朝汐的拼音统一写 Zhaoxi", importance=0.1, relevance=0.0, pinned=True
    )
    await service.maintain()
    await service.maintain()
    assert (await service.require(record.id)).status == MemoryStatus.COLD
    forgotten = await service.forget(record.id)
    assert forgotten.status == MemoryStatus.FORGOTTEN


@pytest.mark.asyncio
async def test_consolidation_creates_semantic_memory_and_archives_details(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    first = await create_memory(service, "今晚不想刷算法", importance=0.4, relevance=0.8)
    second = await create_memory(service, "晚上还是开发舒服", importance=0.5, relevance=0.9)
    third = await create_memory(service, "今晚又选择开发", importance=0.3, relevance=0.8)
    consolidated = await service.consolidate(
        [first.id, second.id, third.id],
        "用户通常更喜欢在晚上开发项目，而不是练习算法。",
        tags=["开发偏好"],
    )
    assert consolidated.kind == MemoryKind.SEMANTIC
    assert consolidated.importance == pytest.approx(0.6)
    assert consolidated.metadata["consolidated_from"] == [first.id, second.id, third.id]
    statuses = [
        (await service.require(memory_id)).status
        for memory_id in [first.id, second.id, third.id]
    ]
    assert statuses == [MemoryStatus.ARCHIVED] * 3


@pytest.mark.asyncio
async def test_requeryable_tool_fact_is_not_copied_by_auto_memory(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    auto = AutoMemory(FakeProvider([ModelResponse(content="unused")]), service)
    decision = await auto.process(
        "昨晚睡了 7 小时。",
        "知道了。",
        source_name="lifehud",
        source_requeryable=True,
        evidence_reference="sleep:2026-08-28",
    )
    assert decision.action == MemoryAction.IGNORE
    assert await service.search(MemoryQuery()) == []


@pytest.mark.asyncio
async def test_memory_decision_lifecycle_actions_are_applied(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    auto = AutoMemory(FakeProvider([ModelResponse(content="unused")]), service)
    first = await create_memory(service, "晚上不想刷算法", importance=0.4, relevance=0.7)
    second = await create_memory(service, "晚上更想开发", importance=0.5, relevance=0.8)

    action = await auto.apply(MemoryDecision(action="archive", target_memory_id=first.id))
    assert action == MemoryAction.ARCHIVE
    assert (await service.require(first.id)).status == MemoryStatus.ARCHIVED

    action = await auto.apply(MemoryDecision(action="reactivate", target_memory_id=first.id))
    assert action == MemoryAction.REACTIVATE
    assert (await service.require(first.id)).status == MemoryStatus.ACTIVE

    action = await auto.apply(MemoryDecision(
        action="consolidate",
        target_memory_ids=[first.id, second.id],
        content="用户晚上通常更偏好开发，而不是刷算法。",
    ))
    assert action == MemoryAction.CONSOLIDATE


@pytest.mark.asyncio
async def test_explicit_keep_creates_high_importance_pinned_memory(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    auto = AutoMemory(FakeProvider([ModelResponse(content="invalid")]), service)
    decision = await auto.process("别忘了这个：朝汐拼音写 Zhaoxi", "好。")
    assert decision.action == MemoryAction.CREATE
    records = await service.search(MemoryQuery(text="Zhaoxi"))
    assert records[0].record.pinned is True
    assert records[0].record.importance >= 0.9


def test_v1_database_is_migrated_to_associative_schema_without_losing_records(tmp_path):
    path = tmp_path / "memory.db"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
        CREATE TABLE schema_version (version INTEGER NOT NULL);
        INSERT INTO schema_version(version) VALUES (1);
        CREATE TABLE memories (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, content TEXT NOT NULL,
            normalized_content TEXT NOT NULL, summary TEXT, tags_json TEXT NOT NULL,
            source_type TEXT NOT NULL, source_ref TEXT, confidence REAL NOT NULL,
            status TEXT NOT NULL, supersedes_id TEXT, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, accessed_at TEXT, metadata_json TEXT NOT NULL
        );
        INSERT INTO memories VALUES (
            'legacy','semantic','旧记忆','旧记忆',NULL,'[]','user',NULL,1.0,
            'active',NULL,'2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00',NULL,'{}'
        );
        """)
    repository = SQLiteMemoryRepository(path)
    record = __import__("asyncio").run(repository.get("legacy"))
    assert record.content == "旧记忆"
    assert record.importance == 0.6
    assert record.relevance == 0.7
    assert record.access_count == 0
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT version FROM schema_version").fetchone()[0] == 5
