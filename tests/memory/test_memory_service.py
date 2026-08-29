import pytest

from zhaoxi.memory.models import MemoryCreate, MemoryQuery, MemoryStatus, MemoryUpdate
from zhaoxi.memory.service import MemoryService
from zhaoxi.memory.sqlite import SQLiteMemoryRepository


@pytest.mark.asyncio
async def test_sqlite_memory_lifecycle_survives_reopen(tmp_path):
    path = tmp_path / "memory.db"
    service = MemoryService(SQLiteMemoryRepository(path))
    created = await service.remember(
        MemoryCreate(content="我喝咖啡不加糖", tags=["Coffee", "preference"])
    )
    assert created.created
    assert created.record.tags == ["coffee", "preference"]

    reopened = MemoryService(SQLiteMemoryRepository(path))
    stored = await reopened.require(created.record.id)
    assert stored.content == "我喝咖啡不加糖"

    updated = await reopened.update(stored.id, MemoryUpdate(content="我喝咖啡只加牛奶"))
    assert updated.normalized_content == "我喝咖啡只加牛奶"
    forgotten = await reopened.forget(stored.id)
    assert forgotten.status == MemoryStatus.FORGOTTEN
    assert await reopened.search(MemoryQuery(text="咖啡")) == []


@pytest.mark.asyncio
async def test_exact_duplicate_does_not_create_another_record(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    first = await service.remember(MemoryCreate(content="项目名是朝汐"))
    second = await service.remember(MemoryCreate(content="  项目名是朝汐  "))
    assert first.record.id == second.record.id
    assert second.duplicate
    assert not second.created


@pytest.mark.asyncio
async def test_chinese_related_query_is_retrieved(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    await service.remember(MemoryCreate(content="我喝咖啡不加糖"))
    await service.remember(MemoryCreate(content="朝汐项目使用 Python"))
    results = await service.search(MemoryQuery(text="我喝咖啡有什么偏好？"))
    assert results
    assert results[0].record.content == "我喝咖啡不加糖"


@pytest.mark.asyncio
async def test_superseding_marks_previous_record(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    old = await service.remember(MemoryCreate(content="我喜欢浅烘咖啡"))
    new = await service.remember(
        MemoryCreate(content="我现在喜欢深烘咖啡", supersedes_id=old.record.id)
    )
    assert (await service.require(old.record.id)).status == MemoryStatus.SUPERSEDED
    assert new.record.supersedes_id == old.record.id


@pytest.mark.asyncio
async def test_possible_conflict_requires_explicit_supersede(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    old = await service.remember(MemoryCreate(content="我喜欢浅烘咖啡"))
    candidate = await service.remember(MemoryCreate(content="我喜欢深烘咖啡"))
    assert not candidate.created
    assert candidate.conflict_candidates[0].id == old.record.id
    assert len(await service.search(MemoryQuery(text="咖啡"))) == 1
