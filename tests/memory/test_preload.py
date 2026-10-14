"""First-request recall privacy and cost guards; live acceptance uses saved data/logs."""
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from zhaoxi.memory.models import MemoryCreate, MemoryStatus, utc_now
from zhaoxi.memory.retrieval import MemoryRetriever
from zhaoxi.memory.service import MemoryService
from zhaoxi.memory.sqlite import SQLiteMemoryRepository


@pytest.mark.asyncio
async def test_local_preload_is_bounded_and_does_not_embed_or_activate(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    for i in range(5):
        await service.remember(MemoryCreate(kind="episodic", content=f"项目 Orion 讨论设计 {i}", source="user"))
    stale = await service.remember(MemoryCreate(kind="state", content="项目 Orion 讨论设计已经取消",
                                               valid_until=utc_now()-timedelta(days=1), source="user"))
    forgotten = await service.remember(MemoryCreate(kind="episodic", content="项目 Orion 讨论设计私人旧稿", source="user"))
    await service.forget(forgotten.record.id)
    service.embedding_provider.embed = AsyncMock(side_effect=AssertionError("Network embedding forbidden"))
    service._activate_selected = AsyncMock(side_effect=AssertionError("Preload must be read only"))
    retriever = MemoryRetriever(service)
    rows = await retriever.preload("之前的项目 Orion 讨论设计")
    assert rows and len(rows) <= 3
    assert all(row.record.status in {MemoryStatus.ACTIVE, MemoryStatus.COLD} for row in rows)
    assert not {stale.record.id, forgotten.record.id} & {row.record.id for row in rows}
    assert len(retriever.format(rows, max_chars=1200)) <= 1200
    service.embedding_provider.embed.assert_not_awaited()
    service._activate_selected.assert_not_awaited()
    assert service.last_retrieval["embedding_status"] == "local_lexical"
    assert await retriever.preload("Completely unrelated Saturn bicycle") == []


@pytest.mark.asyncio
async def test_preload_skips_oversize_fact_without_truncating_it(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    await service.remember(MemoryCreate(kind="episodic", content="Orion budget " + "x"*1500, source="user"))
    await service.remember(MemoryCreate(kind="episodic", content="Orion budget is small", source="user"))
    rows = await MemoryRetriever(service).preload("Orion budget")
    assert len(rows) == 1 and rows[0].record.content == "Orion budget is small"

@pytest.mark.asyncio
async def test_tool_recall_keeps_preload_candidates_without_duplicates(tmp_path):
    from zhaoxi.observability import ActionTrace, bind_action_trace
    from zhaoxi.tools.builtin.memory_tools import SearchMemoriesTool, SearchMemoryInput
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    await service.remember(MemoryCreate(kind="episodic", content="Orion first fact", source="user"))
    await service.remember(MemoryCreate(kind="episodic", content="Saturn second fact", source="user"))
    preloaded = await MemoryRetriever(service).preload("Orion first fact")
    trace = ActionTrace('memory-trace', 'memory-request')
    with bind_action_trace(trace):
        trace.record_memory_candidates(preloaded, source="preload")
        tool = SearchMemoriesTool(service)
        result = await tool.execute(SearchMemoryInput(query="Saturn second fact"))
        assert result.success
        await tool.execute(SearchMemoryInput(query="Saturn second fact"))
        candidates = trace.metrics()["memory_candidates"]
        assert len(candidates) == 2 and {x['retrieval_source'] for x in candidates} == {'preload','tool'}
        assert [x['rank'] for x in candidates] == [1,2]
