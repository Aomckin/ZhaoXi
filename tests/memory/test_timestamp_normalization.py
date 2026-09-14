"""Regression for model/legacy naive timestamps breaking retrieval and AutoMemory."""
from datetime import UTC, datetime, timedelta
import pytest
from zhaoxi.memory.models import MemoryCreate, MemoryQuery, MemoryCluster, MemoryEdge, MemorySearchResult
from zhaoxi.memory.retrieval import MemoryRetriever
from zhaoxi.memory.service import MemoryService
from zhaoxi.memory.sqlite import SQLiteMemoryRepository
from zhaoxi.memory.lifecycle import MemoryLifecyclePolicy


@pytest.mark.asyncio
async def test_naive_episode_survives_search_and_following_memory_write(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / 'memory.db'))
    record = (await service.remember(MemoryCreate(content='用户晚上吃了面条', kind='episodic',
        event_at='2026-09-08T12:00:00', valid_from='2026-09-08T00:00:00'))).record
    results = await service.search(MemoryQuery(text='晚上吃', now='2026-09-08T13:00:00'))
    assert results and record.event_at.tzinfo is not None
    second = await service.remember(MemoryCreate(content='用户晚上喝了一杯水', kind='episodic',
        event_at='2026-09-08T21:00:00+08:00'))
    assert second.record.event_at == datetime(2026, 9, 8, 13, tzinfo=UTC)
    record.metadata['activation_decayed_at'] = '2026-09-07T00:00:00'
    MemoryLifecyclePolicy().decay(record, datetime(2026, 9, 8, tzinfo=UTC))


@pytest.mark.asyncio
async def test_legacy_naive_database_dates_normalized_when_read(tmp_path):
    import sqlite3
    path = tmp_path / 'memory.db'
    service = MemoryService(SQLiteMemoryRepository(path))
    record = (await service.remember(MemoryCreate(content='旧记录', kind='episodic'))).record
    with sqlite3.connect(path) as connection:
        connection.execute('UPDATE memories SET event_at=?, created_at=?, updated_at=? WHERE id=?',
            ('2026-09-08T12:00:00', '2026-09-08T00:00:00', '2026-09-08T00:00:00', record.id))
    restored = await service.require(record.id)
    assert restored.event_at.tzinfo is not None and restored.created_at.tzinfo is not None
    assert await service.search(MemoryQuery(text='旧记录'))


@pytest.mark.asyncio
async def test_imported_diary_record_time_does_not_imply_event_time_or_agent_presence(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / 'memory.db'))
    known = datetime(2026, 9, 14, 6, tzinfo=UTC)
    result = await service.remember(MemoryCreate(
        content='旧日记写着用户在 2020 年独自旅行。',
        kind='episodic',
        source='imported_diary',
        recorded_at=known,
        known_at=known,
    ))
    record = result.record
    assert record.event_at is None
    assert record.recorded_at == known
    assert record.known_at == known
    assert record.source == 'imported_diary'
    formatted = MemoryRetriever(service).format([MemorySearchResult(record=record)])
    assert 'event_at=""' in formatted
    assert 'recorded_at="2026-09-14T06:00:00+00:00"' in formatted
    assert '不得据此推断朝汐当时在场、存在或亲历' in formatted
