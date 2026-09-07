import json

import pytest

from conftest import FakeProvider
from zhaoxi.cognitive.memory_decision import AutoMemory
from zhaoxi.memory.consolidation import AutoConsolidationConfig, AutoConsolidator
from zhaoxi.memory.models import (
    MemoryCandidate,
    MemoryCreate,
    MemoryKind,
    MemoryQuery,
    MemoryShape,
    MemoryStatus,
)
from zhaoxi.memory.service import MemoryService
from zhaoxi.memory.sqlite import SQLiteMemoryRepository
from zhaoxi.models.types import ModelResponse


async def _episodes(service, contents, tag="夜间开发"):
    records = []
    for content in contents:
        result = await service.remember(MemoryCreate(
            kind=MemoryKind.EPISODIC, content=content, tags=[tag], entities=["朝汐开发"],
        ))
        records.append(result.record)
    return records


@pytest.mark.asyncio
async def test_automatic_consolidation_threshold_uses_one_batched_llm_call_and_keeps_episodes(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    episodes = await _episodes(service, [
        "晚上开发效率高。", "深夜完成任务。", "晚上明显更专注。",
    ])
    cluster = next(item for item in await service.repository.list_clusters() if item.active)
    response = {"decisions": [{
        "cluster_id": cluster.id, "action": "create_semantic",
        "content": "用户通常在夜间更容易进入高专注开发状态。",
        "evidence_memory_ids": [item.id for item in episodes], "confidence": 0.9,
    }]}
    provider = FakeProvider([ModelResponse(content=json.dumps(response, ensure_ascii=False))])
    consolidator = AutoConsolidator(provider, service, AutoConsolidationConfig(
        after_episodes=3, interval_hours=24, min_evidence=3,
    ))
    assert await consolidator.maybe_run()
    assert len(provider.calls) == 1
    records = await service.repository.list_cluster_members(cluster.id)
    semantics = [item for item in records if item.kind == MemoryKind.SEMANTIC]
    assert len(semantics) == 1
    assert semantics[0].evidence_memory_ids == [item.id for item in episodes]
    statuses = [(await service.require(item.id)).status for item in episodes]
    assert statuses == [MemoryStatus.ACTIVE] * 3


@pytest.mark.asyncio
async def test_automatic_consolidation_without_candidate_makes_no_llm_call(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    await _episodes(service, ["只发生过一次。"], tag="孤立事件")
    provider = FakeProvider([ModelResponse(content="不应调用")])
    consolidator = AutoConsolidator(provider, service, AutoConsolidationConfig(
        after_episodes=2, interval_hours=24, min_evidence=3,
    ))
    assert not await consolidator.maybe_run()
    assert provider.calls == []
    diagnostics = await service.diagnostics()
    assert diagnostics["consolidation_checks"] == 1
    assert diagnostics["consolidation_llm_calls"] == 0


@pytest.mark.asyncio
async def test_existing_semantic_gets_new_evidence_instead_of_duplicate(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    first = await _episodes(service, ["周一晚上开发很专注。", "周二深夜完成开发。", "周三晚上效率很高。"])
    semantic = await service.consolidate(
        [item.id for item in first], "用户通常在夜间更容易专注开发。", tags=["夜间开发"],
    )
    more = await _episodes(service, ["周四夜里进入心流。", "周五晚上又高效完成任务。"])
    cluster = next(item for item in await service.repository.list_clusters() if item.id == semantic.cluster_id)
    response = {"decisions": [{
        "cluster_id": cluster.id, "action": "update_semantic", "semantic_id": semantic.id,
        "evidence_memory_ids": [item.id for item in more], "confidence": 0.95,
    }]}
    provider = FakeProvider([ModelResponse(content=json.dumps(response))])
    consolidator = AutoConsolidator(provider, service, AutoConsolidationConfig(
        after_episodes=2, interval_hours=24, min_evidence=3,
    ))
    assert await consolidator.maybe_run()
    updated = await service.require(semantic.id)
    assert updated.evidence_memory_ids == [item.id for item in [*first, *more]]
    members = await service.repository.list_cluster_members(cluster.id)
    assert sum(item.kind == MemoryKind.SEMANTIC for item in members) == 1


@pytest.mark.asyncio
async def test_open_cluster_uses_shared_entity_and_centroid_without_topic_hint(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    values = [
        ("今天出去拍了晚霞。", "晚霞", "摄影活动"),
        ("最近开始研究相机。", "相机", "摄影活动"),
        ("昨天又去拍照了。", "拍照", "摄影活动"),
        ("长焦镜头挺有意思。", "镜头", "摄影活动"),
    ]
    records = []
    for content, tag, entity in values:
        records.append((await service.remember(MemoryCreate(
            kind="episodic", content=content, tags=[tag], entities=[entity],
        ))).record)
    refreshed = [await service.require(item.id) for item in records]
    assert len({item.cluster_id for item in refreshed}) == 1
    cluster = next(item for item in await service.repository.list_clusters() if item.id == refreshed[0].cluster_id)
    assert cluster.member_count == 4
    assert cluster.centroid_embedding
    assert cluster.topic not in service.TOPIC_HINTS


@pytest.mark.asyncio
async def test_high_confidence_clusters_merge_without_changing_memories(tmp_path):
    service = MemoryService(
        SQLiteMemoryRepository(tmp_path / "memory.db"),
        cluster_match_threshold=0.60, cluster_merge_threshold=0.62,
    )
    first = (await service.remember(MemoryCreate(
        kind="episodic", content="拍摄晚霞。", tags=["摄影"], entities=["相机"],
    ))).record
    second = (await service.remember(MemoryCreate(
        kind="episodic", content="外出拍照。", tags=["拍照"], entities=["镜头"],
    ))).record
    assert (await service.require(first.id)).cluster_id != (await service.require(second.id)).cluster_id
    await service.remember(MemoryCreate(
        kind="episodic", content="用相机和镜头拍摄照片。",
        tags=["摄影", "拍照"], entities=["相机", "镜头"],
    ))
    clusters = await service.repository.list_clusters()
    assert sum(item.active for item in clusters) == 1
    assert any(not item.active and item.merged_into_id for item in clusters)
    assert (await service.require(first.id)).content == "拍摄晚霞。"
    assert (await service.require(second.id)).content == "外出拍照。"


@pytest.mark.asyncio
async def test_auto_memory_edge_resolves_entities_aliases_and_builds_retrievable_graph(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    payload = {"candidates": [{
        "kind": "relationship", "shape": "edge", "content": "暗苟为朝汐命名。",
        "source_entity": "暗苟", "target_entity": "Zhaoxi", "relation_label": "命名",
        "confidence": 0.95, "importance": 0.8,
    }]}
    provider = FakeProvider([ModelResponse(content=json.dumps(payload, ensure_ascii=False))])
    decision = await AutoMemory(provider, service).process("我给朝汐取了这个名字。", "原来如此。")
    assert decision.applied_count == 1
    edge_memory = (await service.repository.list_records(MemoryQuery(limit=10)))[0]
    assert edge_memory.shape == MemoryShape.EDGE
    entities = await service.repository.list_entities()
    assert {item.canonical_name for item in entities} == {"暗苟", "朝汐"}
    assert (await service.resolve_entity("朝汐")).id == (await service.resolve_entity("Zhaoxi")).id
    edges = await service.repository.edges_for([edge_memory.id], 0)
    assert len(edges) == 2
    diagnostics = await service.diagnostics()
    assert diagnostics["edge_memories"] == 1
    assert diagnostics["entity_nodes"] == 2
    assert diagnostics["edge_extraction_success"] == 1
    prompt = provider.calls[0][0].content
    assert "source_entity" in prompt and "target_entity" in prompt
    assert "绝不输出或猜测 source_node_id" in prompt
    second = (await service.remember_candidates([MemoryCandidate(
        kind="relationship", shape="edge", content="她喜欢夏天。",
        source_entity="朝汐", target_entity="夏天", relation_label="喜欢",
        confidence=0.9, importance=0.7,
    )]))[0].record
    recalled = await service.search(MemoryQuery(text="命名者是谁？", limit=8, max_hops=2))
    expanded = next(item for item in recalled if item.record.id == second.id)
    assert expanded.graph_hop == 2
    assert expanded.seed_memory_id == edge_memory.id
    assert expanded.edge_relation == "about"


@pytest.mark.asyncio
async def test_malformed_edge_falls_back_to_node_without_bad_graph_edge(tmp_path):
    service = MemoryService(SQLiteMemoryRepository(tmp_path / "memory.db"))
    result = await service.remember_candidates([MemoryCandidate(
        kind="relationship", shape="edge", content="某个关系描述不完整。",
        source_entity="暗苟", relation_label="喜欢",
    )])
    assert result[0].record.shape == MemoryShape.NODE
    assert await service.repository.edges_for([result[0].record.id], 0) == []
    diagnostics = await service.diagnostics()
    assert diagnostics["edge_extraction_fallback"] == 1
