"""Business rules for associative long-term memory."""

from collections import defaultdict
from datetime import datetime
import re

from zhaoxi.errors import MemoryNotFoundError
from zhaoxi.memory.embedding import LocalHashEmbeddingProvider, cosine
from zhaoxi.memory.lifecycle import MemoryLifecyclePolicy
from zhaoxi.memory.models import (
    MemoryCandidate,
    MemoryCluster,
    MemoryCreate,
    MemoryEdge,
    MemoryEmbedding,
    MemoryEntity,
    MemoryKind,
    MemoryQuery,
    MemoryRecord,
    MemoryRelation,
    MemoryShape,
    MemorySearchResult,
    MemoryStatus,
    MemoryUpdate,
    MemoryWriteResult,
    utc_now,
)
from zhaoxi.memory.repository import MemoryRepository


def normalize_memory_text(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", value.casefold())


class MemoryService:
    """Validate, organize, relate, retrieve and consolidate memories."""

    TOPIC_HINTS = {
        "饮酒": ("啤酒", "白朗姆", "朗姆", "金酒", "威士忌", "喝酒", "酒"),
        "烹饪": ("做饭", "烹饪", "炒", "煮", "食谱"),
        "Zhaoxi开发": ("朝汐", "zhaoxi", "开发", "代码", "memory"),
        "求职": ("秋招", "面试", "简历", "求职", "八股"),
        "舞萌": ("舞萌", "maimai"),
    }
    EXPLICIT_RECALL_MARKERS = ("记得", "以前", "之前", "那次", "发生过什么", "都喝过什么")
    CANONICAL_ALIASES = {"朝汐": {"朝汐", "zhaoxi"}}

    def __init__(
        self,
        repository: MemoryRepository,
        lifecycle_policy: MemoryLifecyclePolicy | None = None,
        embedding_provider: LocalHashEmbeddingProvider | None = None,
        cluster_embedding_enabled: bool = True,
        cluster_match_threshold: float = 0.38,
        cluster_merge_threshold: float = 0.84,
        edge_extraction_enabled: bool = True,
    ) -> None:
        self.repository = repository
        self.lifecycle_policy = lifecycle_policy or MemoryLifecyclePolicy()
        self.embedding_provider = embedding_provider or LocalHashEmbeddingProvider()
        self.cluster_embedding_enabled = cluster_embedding_enabled
        self.cluster_match_threshold = cluster_match_threshold
        self.cluster_merge_threshold = cluster_merge_threshold
        self.edge_extraction_enabled = edge_extraction_enabled

    async def remember(self, value: MemoryCreate) -> MemoryWriteResult:
        normalized = normalize_memory_text(value.content)
        duplicate = await self.repository.find_by_normalized_content(normalized)
        if duplicate and duplicate.status not in {MemoryStatus.FORGOTTEN, MemoryStatus.SUPERSEDED}:
            return MemoryWriteResult(record=duplicate, created=False, duplicate=True)

        conflicts: list[MemoryRecord] = []
        if value.kind in {MemoryKind.SEMANTIC, MemoryKind.STATE, MemoryKind.RELATIONSHIP}:
            related = await self.repository.search(
                MemoryQuery(text=value.content, kind=value.kind, limit=3, per_cluster_limit=3)
            )
            conflicts = [item.record for item in related if item.text_score >= 0.40]
        if conflicts and not value.supersedes_id:
            return MemoryWriteResult(record=conflicts[0], created=False, conflict_candidates=conflicts)

        data = value.model_dump(exclude={"relevance"})
        recorded_at = value.recorded_at or utc_now()
        data.update({
            "recorded_at": recorded_at,
            "known_at": value.known_at or recorded_at,
            "source": value.source or value.source_name or value.source_type.value,
        })
        record = MemoryRecord(**data, normalized_content=normalized)
        if value.supersedes_id:
            previous = await self.require(value.supersedes_id)
            previous.status = MemoryStatus.SUPERSEDED
            previous.updated_at = utc_now()
            await self.repository.save(previous)
        stored = await self.repository.create(record)
        await self._ensure_embedding(stored)
        await self._organize(stored)
        if stored.kind == MemoryKind.EPISODIC:
            await self._increment_runtime("episodes_since_consolidation_check")
        if value.supersedes_id:
            await self.repository.save_edge(MemoryEdge(
                source_id=stored.id, target_id=value.supersedes_id,
                relation=MemoryRelation.SUPERSEDES, weight=1.0, confidence=stored.confidence,
                evidence_memory_ids=[stored.id, value.supersedes_id],
            ))
            await self.repository.save_edge(MemoryEdge(
                source_id=stored.id, target_id=value.supersedes_id,
                relation=MemoryRelation.CONTRADICTS, weight=0.85, confidence=stored.confidence,
                evidence_memory_ids=[stored.id, value.supersedes_id],
            ))
        return MemoryWriteResult(record=await self.require(stored.id), created=True, conflict_candidates=conflicts)

    async def remember_candidates(self, candidates: list[MemoryCandidate]) -> list[MemoryWriteResult]:
        results: list[MemoryWriteResult] = []
        for candidate in candidates:
            edge_requested = candidate.shape == MemoryShape.EDGE
            edge_valid = bool(candidate.source_entity and candidate.target_entity and candidate.relation_label)
            prepared = candidate
            if edge_requested and (not self.edge_extraction_enabled or not edge_valid):
                prepared = candidate.model_copy(update={"shape": MemoryShape.NODE})
                await self._increment_runtime("edge_extraction_fallback")
            result = await self.remember(MemoryCreate(**prepared.model_dump(exclude={
                "relation", "relation_label", "source_entity", "target_entity",
                "source_node_id", "target_node_id", "relevance",
            })))
            results.append(result)
            if result.created and edge_requested and edge_valid and self.edge_extraction_enabled:
                source = await self.resolve_entity(candidate.source_entity or "")
                target = await self.resolve_entity(candidate.target_entity or "")
                relation = candidate.relation or MemoryRelation.ASSOCIATED_WITH.value
                known = {item.value for item in MemoryRelation}
                await self.repository.save_edge(MemoryEdge(
                    source_id=source.id, target_id=target.id,
                    relation=relation if relation in known else MemoryRelation.ASSOCIATED_WITH,
                    relation_label=candidate.relation_label or (relation if relation not in known else None),
                    confidence=candidate.confidence, weight=candidate.importance,
                    evidence_memory_ids=[result.record.id],
                    valid_from=candidate.valid_from, valid_until=candidate.valid_until,
                ))
                for entity in (source, target):
                    await self.repository.save_edge(MemoryEdge(
                        source_id=result.record.id, target_id=entity.id, relation=MemoryRelation.ABOUT,
                        relation_label=entity.canonical_name, weight=0.9, confidence=candidate.confidence,
                        evidence_memory_ids=[result.record.id], valid_from=candidate.valid_from,
                        valid_until=candidate.valid_until,
                    ))
                await self._increment_runtime("edge_extraction_success")
        return results

    async def resolve_entity(self, name: str) -> MemoryEntity:
        normalized = normalize_memory_text(name)
        canonical_name = name.strip()
        aliases = {canonical_name}
        for canonical, known_aliases in self.CANONICAL_ALIASES.items():
            normalized_aliases = {normalize_memory_text(item) for item in known_aliases}
            if normalized in normalized_aliases:
                canonical_name, aliases = canonical, set(known_aliases)
                break
        entities = await self.repository.list_entities()
        for entity in entities:
            names = {entity.normalized_name, *(normalize_memory_text(item) for item in entity.aliases)}
            if normalized in names or normalize_memory_text(canonical_name) in names:
                merged_aliases = list(dict.fromkeys([*entity.aliases, *aliases, name.strip()]))
                if merged_aliases != entity.aliases:
                    entity.aliases = merged_aliases
                    entity.updated_at = utc_now()
                    await self.repository.save_entity(entity)
                return entity
        return await self.repository.save_entity(MemoryEntity(
            canonical_name=canonical_name, normalized_name=normalize_memory_text(canonical_name),
            aliases=list(dict.fromkeys([*aliases, name.strip()])),
        ))

    async def get(self, memory_id: str) -> MemoryRecord | None:
        return await self.repository.get(memory_id)

    async def require(self, memory_id: str) -> MemoryRecord:
        record = await self.get(memory_id)
        if record is None:
            raise MemoryNotFoundError(f"记忆不存在：{memory_id}")
        return record

    async def search(self, query: MemoryQuery) -> list[MemorySearchResult]:
        if not query.text:
            return await self.repository.search(query)
        now = query.now or utc_now()
        explicit = query.explicit_recall or any(marker in query.text for marker in self.EXPLICIT_RECALL_MARKERS)
        candidate_query = query.model_copy(deep=True)
        if query.statuses == [MemoryStatus.ACTIVE]:
            candidate_query.statuses = [MemoryStatus.ACTIVE, MemoryStatus.COLD]
            if explicit:
                candidate_query.statuses += [MemoryStatus.DORMANT, MemoryStatus.ARCHIVED, MemoryStatus.SUPERSEDED]
        candidate_query.limit = min(max(query.limit * 30, 200), 100)
        records = await self.repository.list_records(candidate_query)
        query_vector = await self.embedding_provider.embed(query.text)
        embeddings = {item.memory_id: item for item in await self.repository.list_embeddings()}
        clusters = {item.id: item for item in await self.repository.list_clusters()}
        hinted_topics = {
            topic for topic, hints in self.TOPIC_HINTS.items()
            if any(hint.casefold() in query.text.casefold() for hint in hints)
        }
        if "喝" in query.text:
            hinted_topics.add("饮酒")
        scored: dict[str, MemorySearchResult] = {}
        for record in records:
            text_score = self._text_score(query.text, record)
            cluster = clusters.get(record.cluster_id or "")
            if cluster and cluster.topic in hinted_topics:
                text_score = max(text_score, 0.45)
            embedding = embeddings.get(record.id)
            semantic_score = cosine(query_vector, embedding.vector) if embedding else 0.0
            time_score = self._time_score(record, now)
            if max(text_score, semantic_score) <= 0.01:
                continue
            contextual = text_score * 0.58 + semantic_score * 0.32 + time_score * 0.10
            if contextual <= 0.015:
                continue
            scored[record.id] = MemorySearchResult(
                record=record, contextual_relevance=round(contextual, 4), text_score=round(text_score, 4),
                semantic_score=round(semantic_score, 4), time_score=round(time_score, 4),
                activation_score=record.activation, importance_score=record.importance,
                cluster=cluster, match_reason="hybrid seed candidate",
            )

        seeds = sorted(scored.values(), key=lambda item: item.contextual_relevance, reverse=True)[:5]
        await self._expand_graph(scored, seeds, query, clusters, now)
        for item in scored.values():
            item.score = round(
                item.text_score * 0.48 + item.semantic_score * 0.27 + item.graph_score * 0.08
                + item.time_score * 0.07 + item.activation_score * 0.06 + item.importance_score * 0.04,
                4,
            )
            item.why_selected = self._why(item)
        ranked = sorted(scored.values(), key=lambda item: (item.score, item.record.updated_at), reverse=True)
        matched_topics = hinted_topics | {
            cluster.topic for cluster in clusters.values()
            if cluster.topic.casefold() in query.text.casefold()
        }
        topic_locked = explicit or len(matched_topics) == 1
        limit_per_cluster = query.limit if topic_locked else query.per_cluster_limit
        selected: list[MemorySearchResult] = []
        cluster_counts: dict[str, int] = defaultdict(int)
        for item in ranked:
            key = item.record.cluster_id or f"unclustered:{item.record.id}"
            if cluster_counts[key] >= limit_per_cluster:
                continue
            cluster_counts[key] += 1
            selected.append(item)
            if len(selected) >= query.limit:
                break
        if query.statuses == [MemoryStatus.ACTIVE]:
            await self._activate_selected(selected, query.min_edge_weight, now)
        return selected

    async def inspect_retrieval(self, query: MemoryQuery) -> list[dict[str, object]]:
        results = await self.search(query)
        return [item.model_dump(mode="json", exclude={"record": {"normalized_content", "metadata"}}) for item in results]

    async def update(self, memory_id: str, patch: MemoryUpdate) -> MemoryRecord:
        record = await self.require(memory_id)
        changes = patch.model_dump(exclude_unset=True, exclude={"relevance"})
        for key, value in changes.items():
            setattr(record, key, value)
        if "content" in changes:
            record.normalized_content = normalize_memory_text(record.content)
        record.updated_at = utc_now()
        stored = await self.repository.save(record)
        if "content" in changes:
            await self._ensure_embedding(stored)
        return stored

    async def forget(self, memory_id: str) -> MemoryRecord:
        record = await self.require(memory_id)
        if record.status != MemoryStatus.FORGOTTEN:
            record.status, record.updated_at = MemoryStatus.FORGOTTEN, utc_now()
            await self.repository.save(record)
        return record

    async def archive(self, memory_id: str) -> MemoryRecord:
        record = await self.require(memory_id)
        if not record.pinned and record.status not in {MemoryStatus.FORGOTTEN, MemoryStatus.SUPERSEDED}:
            record.status, record.updated_at = MemoryStatus.ARCHIVED, utc_now()
            await self.repository.save(record)
        return record

    async def reactivate(self, memory_id: str) -> MemoryRecord:
        record = await self.require(memory_id)
        if record.status in {MemoryStatus.FORGOTTEN, MemoryStatus.SUPERSEDED}:
            return record
        record.status = MemoryStatus.ACTIVE
        self.lifecycle_policy.activate(record)
        record.updated_at = utc_now()
        return await self.repository.save(record)

    async def set_pinned(self, memory_id: str, pinned: bool = True) -> MemoryRecord:
        record = await self.require(memory_id)
        record.pinned = pinned
        if pinned:
            record.importance = max(record.importance, 0.9)
            if record.status in {MemoryStatus.COLD, MemoryStatus.DORMANT, MemoryStatus.ARCHIVED}:
                record.status = MemoryStatus.ACTIVE
        record.updated_at = utc_now()
        return await self.repository.save(record)

    async def maintain(self, limit: int = 100) -> list[MemoryRecord]:
        records = await self.repository.list_records(MemoryQuery(
            statuses=[MemoryStatus.ACTIVE, MemoryStatus.COLD, MemoryStatus.DORMANT, MemoryStatus.ARCHIVED],
            limit=min(limit, 100),
        ))
        changed: list[MemoryRecord] = []
        now = utc_now()
        for record in records:
            if self.lifecycle_policy.maintain(record, now):
                await self.repository.save(record)
                changed.append(record)
        # Only exact, timeless semantic duplicates are safe to retire without a model.
        groups: dict[tuple[MemoryKind, str], list[MemoryRecord]] = defaultdict(list)
        for record in records:
            if (record.kind in {MemoryKind.SEMANTIC, MemoryKind.RELATIONSHIP}
                    and record.status not in {MemoryStatus.FORGOTTEN, MemoryStatus.SUPERSEDED}
                    and record.valid_from is None and record.valid_until is None):
                groups[(record.kind, normalize_memory_text(record.content))].append(record)
        for duplicates in groups.values():
            if len(duplicates) < 2:
                continue
            survivor = max(duplicates, key=lambda item: (item.pinned, len(item.evidence_memory_ids),
                                                        item.confidence, -item.created_at.timestamp()))
            for duplicate in duplicates:
                if duplicate.id == survivor.id or duplicate.pinned:
                    continue
                duplicate.status = MemoryStatus.SUPERSEDED
                duplicate.updated_at = now
                await self.repository.save(duplicate)
                await self.repository.save_edge(MemoryEdge(
                    source_id=survivor.id, target_id=duplicate.id,
                    relation=MemoryRelation.SUPERSEDES, weight=1.0, confidence=1.0,
                    evidence_memory_ids=[survivor.id, duplicate.id],
                ))
                changed.append(duplicate)
        # Repair explicit conflict links and missing organization from older records.
        for record in records:
            if record.status in {MemoryStatus.FORGOTTEN, MemoryStatus.SUPERSEDED}:
                continue
            if record.supersedes_id:
                previous = await self.repository.get(record.supersedes_id)
                if previous and previous.status not in {MemoryStatus.FORGOTTEN, MemoryStatus.SUPERSEDED}:
                    previous.status = MemoryStatus.SUPERSEDED
                    previous.updated_at = now
                    await self.repository.save(previous)
                    await self.repository.save_edge(MemoryEdge(
                        source_id=record.id, target_id=previous.id,
                        relation=MemoryRelation.SUPERSEDES, weight=1.0,
                        confidence=record.confidence, evidence_memory_ids=[record.id, previous.id],
                    ))
                    changed.append(previous)
            if (record.cluster_id is None and record.status in {MemoryStatus.ACTIVE, MemoryStatus.COLD}
                    and record.kind in {MemoryKind.SEMANTIC, MemoryKind.RELATIONSHIP}):
                await self._ensure_embedding(record)
                await self._organize(record)
                if record.cluster_id is not None:
                    changed.append(record)
        return changed

    async def consolidate(self, memory_ids: list[str], content: str, *, tags: list[str] | None = None) -> MemoryRecord:
        unique_ids = list(dict.fromkeys(memory_ids))
        if len(unique_ids) < 2:
            raise ValueError("至少需要两条记忆才能进行 Consolidation。")
        records = [await self.require(memory_id) for memory_id in unique_ids]
        if sum(record.kind == MemoryKind.EPISODIC for record in records) < 2:
            # Legacy callers can still consolidate, but the provenance remains explicit.
            pass
        result = await self.remember(MemoryCreate(
            content=content, kind=MemoryKind.SEMANTIC,
            tags=tags or list(dict.fromkeys(tag for record in records for tag in record.tags)),
            entities=list(dict.fromkeys(entity for record in records for entity in record.entities)),
            importance=min(1.0, max(record.importance for record in records) + 0.1),
            activation=max(record.activation for record in records), confidence=min(record.confidence for record in records),
            source_type=records[0].source_type, source_ref="memory_consolidation",
            evidence_reference=",".join(unique_ids), evidence_memory_ids=unique_ids, derived_at=utc_now(),
            metadata={"consolidated_from": unique_ids},
        ))
        semantic = result.record
        if not result.created:
            semantic.evidence_memory_ids = list(dict.fromkeys([*semantic.evidence_memory_ids, *unique_ids]))
            semantic.derived_at = semantic.derived_at or utc_now()
            semantic.metadata = {**semantic.metadata, "consolidated_from": semantic.evidence_memory_ids}
            semantic = await self.repository.save(semantic)
        for record in records:
            await self.repository.save_edge(MemoryEdge(
                source_id=record.id, target_id=semantic.id, relation=MemoryRelation.EVIDENCE_FOR,
                weight=0.95, confidence=record.confidence, evidence_memory_ids=[record.id],
            ))
            await self.repository.save_edge(MemoryEdge(
                source_id=semantic.id, target_id=record.id, relation=MemoryRelation.DERIVED_FROM,
                weight=0.95, confidence=semantic.confidence, evidence_memory_ids=[record.id],
            ))
            if record.kind != MemoryKind.EPISODIC and not record.pinned:
                record.status = MemoryStatus.ARCHIVED
                record.updated_at = utc_now()
                await self.repository.save(record)
        await self.repository.set_runtime("last_consolidation_at", utc_now().isoformat())
        return semantic

    async def diagnostics(self) -> dict[str, object]:
        return await self.repository.diagnostics()

    async def _increment_runtime(self, key: str, amount: int = 1) -> int:
        current = int(await self.repository.get_runtime(key) or 0) + amount
        await self.repository.set_runtime(key, str(current))
        return current

    async def _ensure_embedding(self, record: MemoryRecord) -> None:
        content_hash = self.embedding_provider.content_hash(record.content)
        current = {item.memory_id: item for item in await self.repository.list_embeddings()}.get(record.id)
        if current and current.embedding_hash == content_hash and current.embedding_model == self.embedding_provider.model:
            return
        await self.repository.save_embedding(MemoryEmbedding(
            memory_id=record.id, embedding_model=self.embedding_provider.model,
            embedding_hash=content_hash, vector=await self.embedding_provider.embed(record.content),
        ))

    async def _organize(self, record: MemoryRecord) -> None:
        topic = self._infer_topic(record)
        clusters = [item for item in await self.repository.list_clusters() if item.active]
        embedding = {item.memory_id: item for item in await self.repository.list_embeddings()}.get(record.id)
        scored = [(self._cluster_match_score(record, item, embedding.vector if embedding else []), item)
                  for item in clusters]
        best_score, cluster = max(scored, default=(0.0, None), key=lambda item: item[0])
        exact_topic = next((item for item in clusters if topic and item.topic.casefold() == topic.casefold()), None)
        if exact_topic is not None:
            best_score, cluster = 1.0, exact_topic
        if cluster is None or best_score < self.cluster_match_threshold:
            cluster = None
        if cluster is None and not topic:
            return
        if cluster is None:
            cluster = MemoryCluster(topic=topic or "未命名主题", tags=record.tags, entities=record.entities)
            best_score = 1.0
        previous_count = cluster.member_count
        cluster.member_count += 1
        if record.event_at is not None:
            cluster.time_start = min(filter(None, (cluster.time_start, record.event_at)), default=record.event_at)
            cluster.time_end = max(filter(None, (cluster.time_end, record.event_at)), default=record.event_at)
        cluster.importance = max(cluster.importance, record.importance)
        cluster.activation = max(cluster.activation, record.activation)
        cluster.tags = list(dict.fromkeys([*cluster.tags, *record.tags]))[:30]
        cluster.entities = list(dict.fromkeys([*cluster.entities, *record.entities]))[:50]
        if embedding and self.cluster_embedding_enabled:
            if not cluster.centroid_embedding:
                cluster.centroid_embedding = embedding.vector
            elif len(cluster.centroid_embedding) == len(embedding.vector):
                cluster.centroid_embedding = [
                    (old * previous_count + new) / max(cluster.member_count, 1)
                    for old, new in zip(cluster.centroid_embedding, embedding.vector)
                ]
        cluster.representative_memory_ids = ([record.id, *cluster.representative_memory_ids])[:3]
        cluster.summary = f"{topic}主题下已记录 {cluster.member_count} 条可追溯记忆。"
        cluster.updated_at = utc_now()
        await self.repository.save_cluster(cluster)
        await self.repository.add_cluster_member(cluster.id, record.id, best_score)
        record.cluster_id = cluster.id
        await self.repository.save(record)
        peers = await self.repository.list_records(MemoryQuery(statuses=[MemoryStatus.ACTIVE, MemoryStatus.COLD], limit=100))
        for peer in [item for item in peers if item.cluster_id == cluster.id and item.id != record.id][:5]:
            await self.repository.save_edge(MemoryEdge(
                source_id=record.id, target_id=peer.id, relation=MemoryRelation.RELATED_TO,
                weight=0.7, confidence=0.9, evidence_memory_ids=[record.id, peer.id],
            ))
        await self._maybe_merge_clusters(cluster)

    def _infer_topic(self, record: MemoryRecord) -> str | None:
        haystack = f"{record.content} {' '.join(record.tags)} {' '.join(record.entities)}".casefold()
        for topic, hints in self.TOPIC_HINTS.items():
            if any(hint.casefold() in haystack for hint in hints):
                return topic
        return record.tags[0] if record.tags else (record.entities[0] if record.entities else None)

    def _cluster_match_score(self, record: MemoryRecord, cluster: MemoryCluster,
                             vector: list[float]) -> float:
        record_tags, cluster_tags = {item.casefold() for item in record.tags}, {item.casefold() for item in cluster.tags}
        record_entities = {normalize_memory_text(item) for item in record.entities}
        cluster_entities = {normalize_memory_text(item) for item in cluster.entities}
        tag_score = self._set_overlap(record_tags, cluster_tags)
        entity_score = self._set_overlap(record_entities, cluster_entities)
        lexical_score = self._text_overlap(
            f"{record.content} {' '.join(record.tags)} {' '.join(record.entities)}",
            f"{cluster.topic} {' '.join(cluster.tags)} {' '.join(cluster.entities)}",
        )
        embedding_score = cosine(vector, cluster.centroid_embedding) if (
            self.cluster_embedding_enabled and vector and cluster.centroid_embedding
        ) else 0.0
        if record.event_at is not None and (cluster.time_start or cluster.time_end):
            distance_days = min(
                abs((record.event_at - edge).total_seconds()) / 86_400
                for edge in (cluster.time_start, cluster.time_end) if edge
            )
            time_score = max(0.0, 1.0 - distance_days / 90.0)
        else:
            time_score = 0.0
        if self.embedding_provider.model == "local-hash-v1":
            weights = (0.35, 0.35, 0.20, 0.05, 0.05)
        else:
            weights = (0.20, 0.20, 0.15, 0.40, 0.05)
        return round(sum(score * weight for score, weight in zip(
            (tag_score, entity_score, lexical_score, embedding_score, time_score), weights
        )), 4)

    async def _maybe_merge_clusters(self, cluster: MemoryCluster) -> None:
        current = cluster
        while True:
            others = [item for item in await self.repository.list_clusters()
                      if item.active and item.id != current.id]
            similarity, other = max(
                ((self._cluster_similarity(current, item), item) for item in others),
                default=(0.0, None), key=lambda item: item[0],
            )
            if other is None or similarity < self.cluster_merge_threshold:
                break
            source, target = (current, other) if current.created_at >= other.created_at else (other, current)
            total = max(source.member_count + target.member_count, 1)
            if source.centroid_embedding and len(source.centroid_embedding) == len(target.centroid_embedding):
                target.centroid_embedding = [
                    (a * target.member_count + b * source.member_count) / total
                    for a, b in zip(target.centroid_embedding, source.centroid_embedding)
                ]
            target.member_count = total
            target.tags = list(dict.fromkeys([*target.tags, *source.tags]))[:30]
            target.entities = list(dict.fromkeys([*target.entities, *source.entities]))[:50]
            target.representative_memory_ids = list(dict.fromkeys(
                [*target.representative_memory_ids, *source.representative_memory_ids]
            ))[:3]
            target.metadata = {**target.metadata, "merged_from": list(dict.fromkeys([
                *target.metadata.get("merged_from", []), source.id,
            ]))}
            target.updated_at = utc_now()
            await self.repository.save_cluster(target)
            await self.repository.merge_clusters(source.id, target.id)
            await self._increment_runtime("cluster_merge_count")
            current = target

    def _cluster_similarity(self, left: MemoryCluster, right: MemoryCluster) -> float:
        lexical = self._text_overlap(
            f"{left.topic} {' '.join(left.tags)} {' '.join(left.entities)}",
            f"{right.topic} {' '.join(right.tags)} {' '.join(right.entities)}",
        )
        embedding = cosine(left.centroid_embedding, right.centroid_embedding)
        shared_tags = self._set_containment({x.casefold() for x in left.tags}, {x.casefold() for x in right.tags})
        shared_entities = self._set_containment(
            {normalize_memory_text(x) for x in left.entities},
            {normalize_memory_text(x) for x in right.entities},
        )
        if self.embedding_provider.model == "local-hash-v1":
            return lexical * 0.25 + shared_tags * 0.30 + shared_entities * 0.30 + embedding * 0.15
        return lexical * 0.20 + shared_tags * 0.15 + shared_entities * 0.20 + embedding * 0.45

    @staticmethod
    def _set_overlap(left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left & right) / len(left | right)

    @staticmethod
    def _set_containment(left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left & right) / min(len(left), len(right))

    @classmethod
    def _text_overlap(cls, left: str, right: str) -> float:
        left_units, right_units = cls._units(left.casefold()), cls._units(right.casefold())
        return len(left_units & right_units) / max(len(left_units | right_units), 1)

    async def _expand_graph(self, scored: dict[str, MemorySearchResult], seeds: list[MemorySearchResult],
                            query: MemoryQuery, clusters: dict[str, MemoryCluster], now: datetime) -> None:
        frontier = {item.record.id: (item.contextual_relevance, item.record.id) for item in seeds}
        visited = set(frontier)
        for hop in range(1, query.max_hops + 1):
            edges = await self.repository.edges_for(list(frontier), query.min_edge_weight)
            next_frontier: dict[str, tuple[float, str]] = {}
            decay = 0.65 if hop == 1 else 0.35
            for edge in edges:
                if (edge.valid_from and now < edge.valid_from) or (edge.valid_until and now > edge.valid_until):
                    continue
                source_in = edge.source_id in frontier
                neighbor = edge.target_id if source_in else edge.source_id
                origin = edge.source_id if source_in else edge.target_id
                if neighbor in visited:
                    continue
                record = await self.repository.get(neighbor)
                origin_score, seed_id = frontier[origin]
                graph_score = origin_score * decay * edge.weight
                if graph_score < 0.02:
                    continue
                if record is None:
                    # Concept nodes are graph-only transit points, never injected as facts.
                    next_frontier[neighbor] = (graph_score, seed_id)
                    visited.add(neighbor)
                    continue
                if record.status in {MemoryStatus.FORGOTTEN, MemoryStatus.SUPERSEDED}:
                    continue
                item = scored.get(neighbor) or MemorySearchResult(
                    record=record, activation_score=record.activation, importance_score=record.importance,
                    time_score=self._time_score(record, now), cluster=clusters.get(record.cluster_id or ""),
                    match_reason=f"graph {hop}-hop",
                )
                item.graph_score = max(item.graph_score, graph_score)
                if graph_score >= item.graph_score:
                    item.seed_memory_id = seed_id
                    item.edge_relation = edge.relation.value
                    item.relation_label = edge.relation_label
                    item.graph_hop = hop
                scored[neighbor] = item
                next_frontier[neighbor] = (graph_score, seed_id)
                visited.add(neighbor)
            frontier = next_frontier
            if not frontier:
                break

    async def _activate_selected(self, selected: list[MemorySearchResult], min_weight: float, now: datetime) -> None:
        strong = [item for item in selected if item.contextual_relevance >= 0.15][:5]
        if not strong:
            return
        for item in strong:
            self.lifecycle_policy.activate(item.record, now, 0.12)
            item.record.updated_at = now
            await self.repository.save(item.record)
        edges = await self.repository.edges_for([item.record.id for item in strong], min_weight)
        boosted: set[str] = set()
        for edge in edges:
            for memory_id in (edge.source_id, edge.target_id):
                if memory_id in boosted or any(item.record.id == memory_id for item in strong):
                    continue
                neighbor = await self.repository.get(memory_id)
                if neighbor and neighbor.status not in {MemoryStatus.FORGOTTEN, MemoryStatus.SUPERSEDED}:
                    neighbor.activation = min(1.0, neighbor.activation + 0.03 * edge.weight)
                    await self.repository.save(neighbor)
                    boosted.add(memory_id)
        if boosted:
            second_edges = await self.repository.edges_for(list(boosted), min_weight)
            strong_ids = {item.record.id for item in strong}
            for edge in second_edges:
                for memory_id in (edge.source_id, edge.target_id):
                    if memory_id in boosted or memory_id in strong_ids:
                        continue
                    neighbor = await self.repository.get(memory_id)
                    if neighbor and neighbor.status not in {MemoryStatus.FORGOTTEN, MemoryStatus.SUPERSEDED}:
                        neighbor.activation = min(1.0, neighbor.activation + 0.008 * edge.weight)
                        await self.repository.save(neighbor)

    @classmethod
    def _text_score(cls, query: str, record: MemoryRecord) -> float:
        target = f"{record.content} {record.summary or ''} {' '.join(record.tags)} {' '.join(record.entities)}".casefold()
        folded = query.casefold().strip()
        if folded in target:
            return 1.0
        query_units = cls._units(folded)
        return len(query_units & cls._units(target)) / max(len(query_units), 1)

    @staticmethod
    def _units(value: str) -> set[str]:
        compact = "".join(character for character in value if character.isalnum())
        units = set(re.findall(r"[a-z0-9_]+", value))
        units.update(compact[index:index + 2] for index in range(max(len(compact) - 1, 0)))
        return units

    @staticmethod
    def _time_score(record: MemoryRecord, now: datetime) -> float:
        if record.valid_from and now < record.valid_from:
            return 0.05
        if record.valid_until and now > record.valid_until:
            return 0.05 if record.kind in {MemoryKind.STATE, MemoryKind.INTENT} else 0.3
        moment = record.event_at or record.last_confirmed_at
        if moment is None:
            return 0.5
        days = max((now - moment).total_seconds() / 86_400, 0)
        return max(0.15, 1.0 / (1.0 + days / 180.0))

    @staticmethod
    def _why(item: MemorySearchResult) -> list[str]:
        reasons = []
        if item.text_score:
            reasons.append(f"keyword={item.text_score:.3f}")
        if item.semantic_score:
            reasons.append(f"embedding={item.semantic_score:.3f}")
        if item.graph_score:
            reasons.append(f"graph={item.graph_score:.3f}")
            reasons.append(
                f"path=seed:{item.seed_memory_id or '-'} hop:{item.graph_hop or '-'} "
                f"relation:{item.edge_relation or '-'} label:{item.relation_label or '-'}"
            )
        if item.cluster:
            reasons.append(f"cluster={item.cluster.topic}")
        reasons.append(f"time={item.time_score:.3f}")
        return reasons
