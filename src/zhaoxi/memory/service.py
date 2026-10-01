"""Business rules for associative long-term memory."""

from collections import defaultdict
from datetime import datetime
import re

from zhaoxi.errors import MemoryNotFoundError
from zhaoxi.memory.embedding import LocalHashEmbeddingProvider, cosine, compatible, embedding_space
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
    RetrievalMode,
    utc_now,
)
from zhaoxi.memory.repository import MemoryRepository


def normalize_memory_text(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", value.casefold())


class MemoryService:
    """Validate, organize, relate, retrieve and consolidate memories."""

    TOPIC_HINTS = {
        "饮酒": ("啤酒", "朗姆", "金酒", "威士忌", "喝酒", "酒量", "伏特加"),
        "烹饪": ("做饭", "烹饪", "食谱", "炒菜"),
        "求职": ("秋招", "面试", "简历", "求职", "网申", "笔试", "招聘", "岗位", "offer", "投递", "亚信", "丘脑"),
        "LifeHUD": ("lifehud", "饮食记录", "睡眠记录", "focus session"),
        "Persona": ("角色设定", "人设", "三视图", "persona"),
        "舞萌": ("舞萌", "maimai"),
        "寝室": ("寝室", "宿舍", "冰箱"),
        "Zhaoxi开发": ("runtime", "运行时", "memory", "记忆系统", "长期记忆", "聚类", "召回", "current cognition",
            "当前认知", "qq", "接口", "联调", "napcat", "mcp", "工具系统", "前端", "后端", "插件", "api", "数据库", "源码", "prompt", "fast gate", "llm", "qq 接入", "接入qq"),
    }
    EXPLICIT_RECALL_MARKERS = ("记得", "以前", "之前", "那次", "发生过什么", "都喝过什么")
    CANONICAL_ALIASES = {"朝汐": {"朝汐", "zhaoxi"}}

    def __init__(
        self,
        repository: MemoryRepository,
        lifecycle_policy: MemoryLifecyclePolicy | None = None,
        embedding_provider: object | None = None,
        cluster_embedding_enabled: bool = True,
        cluster_match_threshold: float = 0.38,
        cluster_merge_threshold: float = 0.84,
        edge_extraction_enabled: bool = True,
        cluster_max_members: int = 80,
    ) -> None:
        self.repository = repository
        self.lifecycle_policy = lifecycle_policy or MemoryLifecyclePolicy()
        self.embedding_provider = embedding_provider or LocalHashEmbeddingProvider()
        self.cluster_embedding_enabled = cluster_embedding_enabled
        self.cluster_match_threshold = cluster_match_threshold
        self.cluster_merge_threshold = cluster_merge_threshold
        self.edge_extraction_enabled = edge_extraction_enabled
        self.cluster_max_members = cluster_max_members
        self.last_retrieval = {}

    async def remember(self, value: MemoryCreate) -> MemoryWriteResult:
        normalized = normalize_memory_text(value.content)
        duplicate = await self.repository.find_by_normalized_content(normalized)
        if duplicate and duplicate.status not in {MemoryStatus.FORGOTTEN, MemoryStatus.SUPERSEDED}:
            refs = list(dict.fromkeys([*duplicate.metadata.get("evidence_refs",[]), *[x for x in (duplicate.source_event_id,duplicate.evidence_reference,value.source_event_id,value.evidence_reference) if x]]))
            duplicate.metadata["evidence_refs"] = refs[-100:]
            duplicate.source_message_ids = list(dict.fromkeys([*duplicate.source_message_ids,*value.source_message_ids,*[x for x in (value.source_message_id,) if x]]))[:100]
            await self.repository.save(duplicate)
            await self._increment_runtime("memory_dedup_exact")
            return MemoryWriteResult(record=duplicate, created=False, duplicate=True)

        if value.source_event_id:
            existing = await self.repository.search(MemoryQuery(text=value.content,kind=value.kind,limit=5,
                statuses=[MemoryStatus.ACTIVE,MemoryStatus.COLD,MemoryStatus.DORMANT,MemoryStatus.ARCHIVED]))
            same = next((x.record for x in existing if x.record.source_event_id == value.source_event_id and x.text_score>=.85), None)
            if same:
                await self._increment_runtime("memory_dedup_same_event")
                return MemoryWriteResult(record=same,created=False,duplicate=True)
        if value.source_ref == "auto_memory":
            semantic_peers=await self.search(MemoryQuery(text=value.content,kind=value.kind,limit=5,
                retrieval_mode=RetrievalMode.EXPLICIT_RECALL),activate=False)
            for item in semantic_peers:
                same_event=bool(value.source_event_id and value.source_event_id==item.record.source_event_id)
                same_entity=bool(value.entities and set(value.entities)&set(item.record.entities))
                if item.semantic_score>=.96 and (same_event or (same_entity and item.text_score>=.70)):
                    refs=[x for x in (value.source_event_id,value.evidence_reference) if x]
                    item.record.metadata["evidence_refs"]=list(dict.fromkeys([*item.record.metadata.get("evidence_refs",[]),*refs]))[-100:]
                    await self.repository.save(item.record)
                    await self._increment_runtime("memory_dedup_near")
                    return MemoryWriteResult(record=item.record,created=False,duplicate=True)
        conflicts: list[MemoryRecord] = []
        if value.kind in {MemoryKind.SEMANTIC, MemoryKind.STATE, MemoryKind.RELATIONSHIP}:
            related = await self.repository.search(
                MemoryQuery(text=value.content, kind=value.kind, limit=3, per_cluster_limit=3)
            )
            for item in related:
                same_event = bool(value.source_event_id and item.record.source_event_id == value.source_event_id)
                same_fact = item.text_score >= 0.88 and item.record.kind == value.kind
                if same_fact and (same_event or item.text_score >= 0.96):
                    await self._increment_runtime("memory_dedup_near")
                    return MemoryWriteResult(record=item.record,created=False,duplicate=True)
            preference = bool(re.match(r"(?:我|用户|暗苟).{0,4}(?:喜欢|不喜欢|习惯|讨厌)",value.content))
            conflicts = [item.record for item in related if item.text_score >= (0.40 if preference or value.kind==MemoryKind.STATE else 0.65)]
        if conflicts and not value.supersedes_id:
            return MemoryWriteResult(record=conflicts[0], created=False, conflict_candidates=conflicts)

        data = value.model_dump()
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
                "source_node_id", "target_node_id",
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

    async def search(self, query: MemoryQuery, *, activate: bool = True) -> list[MemorySearchResult]:
        from zhaoxi.memory.search import retrieve
        return await retrieve(self, query, activate)

    async def inspect_retrieval(self, query: MemoryQuery) -> list[dict[str, object]]:
        results = await self.search(query, activate=False)
        inspected = []
        for item in results:
            value = item.model_dump(mode="json", exclude={"record": {"normalized_content", "metadata"}})
            value["record"]["metadata"] = {key:item.record.metadata[key] for key in
                ("decision","reason","evidence_refs","evidence_scope","activation_history","lifecycle_reason","cluster_reason")
                if key in item.record.metadata}
            inspected.append(value)
        return inspected

    async def update(self, memory_id: str, patch: MemoryUpdate) -> MemoryRecord:
        record = await self.require(memory_id)
        changes = patch.model_dump(exclude_unset=True)
        for key, value in changes.items():
            setattr(record, key, value)
        if "content" in changes:
            record.normalized_content = normalize_memory_text(record.content)
        record.updated_at = utc_now()
        stored = await self.repository.save(record)
        if any(key in changes for key in ("content","tags","entities")):
            previous_cluster=stored.cluster_id
            if previous_cluster:
                with self.repository._connect() as db:
                    db.execute("DELETE FROM memory_cluster_members WHERE memory_id=?",(stored.id,))
                    db.execute("UPDATE memories SET cluster_id=NULL WHERE id=?",(stored.id,))
                stored.cluster_id=None
                from zhaoxi.memory.clustering import refresh
                cluster=next((c for c in await self.repository.list_clusters() if c.id==previous_cluster),None)
                if cluster:
                    members=await self.repository.list_cluster_members(cluster.id)
                    if len(members)<2:
                        for member in members:
                            member.cluster_id=None
                            await self.repository.save(member)
                        with self.repository._connect() as db:db.execute('DELETE FROM memory_cluster_members WHERE cluster_id=?',(cluster.id,))
                        cluster.active=False
                    await refresh(self,cluster,members)
            await self._ensure_embedding(stored)
            await self._organize(stored)
            return await self.require(stored.id)
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
        record.activation=max(record.activation,self.lifecycle_policy.activation_active_threshold)
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
        cursor = int(await self.repository.get_runtime("maintenance_offset") or 0)
        batch = MemoryQuery(statuses=[MemoryStatus.ACTIVE, MemoryStatus.COLD, MemoryStatus.DORMANT, MemoryStatus.ARCHIVED], limit=min(limit,100), offset=cursor)
        records = await self.repository.list_records(batch)
        if not records and cursor:
            batch.offset=0
            records=await self.repository.list_records(batch)
        await self.repository.set_runtime("maintenance_offset",str(batch.offset+len(records) if len(records)==batch.limit else 0))
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
        from zhaoxi.memory.migration import split_oversized_clusters
        await split_oversized_clusters(self)
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
            activation=0.40, confidence=min(record.confidence for record in records),
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
        result=await self.repository.diagnostics()
        keys=("owner_turns","auto_memory_triggered","auto_memory_generated","auto_memory_accepted",
              "auto_memory_written","auto_memory_cluster_assigned","auto_memory_length_failures",
              "auto_memory_backpressure","memory_dedup_exact","memory_dedup_near","memory_dedup_same_event","cluster_split_count")
        result["funnel"]={k:int(await self.repository.get_runtime(k) or 0) for k in keys}
        turns=result["funnel"]["owner_turns"]
        result["memories_per_100_owner_turns"]=round(result["funnel"]["auto_memory_written"]*100/turns,2) if turns else 0
        from zhaoxi.reliability.media import database_metrics
        result["database"]=database_metrics(self.repository.path)
        return result

    async def _increment_runtime(self, key: str, amount: int = 1) -> int:
        current = int(await self.repository.get_runtime(key) or 0) + amount
        await self.repository.set_runtime(key, str(current))
        return current

    async def _ensure_embedding(self, record: MemoryRecord) -> None:
        content_hash = self.embedding_provider.content_hash(record.content)
        current = (await self.repository.embeddings_for([record.id])).get(record.id)
        if current and current.embedding_hash == content_hash and compatible(self.embedding_provider, current):
            return
        await self.repository.save_embedding(MemoryEmbedding(
            memory_id=record.id, embedding_model=self.embedding_provider.model,
            embedding_hash=content_hash, vector=await self.embedding_provider.embed(record.content),
            embedding_version=embedding_space(self.embedding_provider)[1], embedding_dim=embedding_space(self.embedding_provider)[2],
        ))

    async def _organize(self, record: MemoryRecord) -> None:
        from zhaoxi.memory.clustering import organize
        await organize(self, record)

    def _infer_topic(self, record: MemoryRecord) -> str | None:
        from zhaoxi.memory.clustering import has_hint
        body = record.content.casefold()
        labels = " ".join([*record.tags, *record.entities]).casefold()
        # Actor names and the word "开发" alone do not establish a domain.
        scores = [(2 * sum(has_hint(body, hint) for hint in hints)
                   + sum(has_hint(labels, hint) for hint in hints), topic)
                  for topic, hints in self.TOPIC_HINTS.items()]
        score, topic = max(scores, key=lambda item: item[0])
        if score:
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
        if not compatible(self.embedding_provider, cluster):
            return 0.0
        type_score = 1.0 if record.kind.value in cluster.metadata.get("kinds", []) else 0.0
        from zhaoxi.memory.clustering import domain_prior
        score = embedding_score*.65 + tag_score*.12 + entity_score*.10 + lexical_score*.05 + time_score*.04 + type_score*.04
        return round(score * domain_prior(self._infer_topic(record), cluster.domain),4)

    async def _maybe_merge_clusters(self, cluster: MemoryCluster) -> None:
        current = cluster
        while True:
            others = [item for item in await self.repository.list_clusters()
                      if item.active and item.id != current.id]
            similarity, other = max(
                ((self._cluster_similarity(current, item), item) for item in others),
                default=(0.0, None), key=lambda item: item[0],
            )
            if other is None or similarity < self.cluster_merge_threshold or current.member_count + other.member_count > self.cluster_max_members:
                break
            source, target = (current, other) if current.created_at >= other.created_at else (other, current)
            target.metadata["merged_from"] = list(dict.fromkeys([
                *target.metadata.get("merged_from", []), source.id,
            ]))
            await self.repository.merge_clusters(source.id, target.id)
            from zhaoxi.memory.clustering import refresh
            members = [r for r in await self.repository.list_cluster_members(target.id)
                       if r.status not in {MemoryStatus.FORGOTTEN, MemoryStatus.SUPERSEDED}]
            await refresh(self, target, members)
            source.active = False
            source.merged_into_id = target.id
            await self.repository.save_cluster(source)
            await self._increment_runtime("cluster_merge_count")
            current = target

    def _cluster_similarity(self, left: MemoryCluster, right: MemoryCluster) -> float:
        lexical = self._text_overlap(
            f"{left.topic} {left.summary} {' '.join(left.tags)} {' '.join(left.entities)}",
            f"{right.topic} {right.summary} {' '.join(right.tags)} {' '.join(right.entities)}",
        )
        embedding = cosine(left.centroid_embedding, right.centroid_embedding)
        shared_tags = self._set_containment({x.casefold() for x in left.tags}, {x.casefold() for x in right.tags})
        shared_entities = self._set_containment(
            {normalize_memory_text(x) for x in left.entities},
            {normalize_memory_text(x) for x in right.entities},
        )
        if (left.embedding_model,left.embedding_version,left.embedding_dim) != (right.embedding_model,right.embedding_version,right.embedding_dim):
            return 0.0
        from zhaoxi.memory.clustering import domain_prior
        return (embedding*.70 + shared_tags*.10 + shared_entities*.10 + lexical*.10)*domain_prior(left.domain,right.domain)

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
                if neighbor not in scored:
                    continue
                record = scored[neighbor].record
                origin_score, seed_id = frontier[origin]
                graph_score = origin_score * decay * edge.weight
                if graph_score < 0.02 or record.status not in query.statuses:
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
        strong=[x for x in selected if x.contextual_relevance>=.15][:5]
        if not strong:return
        for item in strong:
            self.lifecycle_policy.activate(item.record,now)
            await self.repository.save(item.record)
        boosted={x.record.id for x in strong}
        cluster_ids=list(dict.fromkeys(x.record.cluster_id for x in strong if x.record.cluster_id))
        if cluster_ids:
            siblings=await self.repository.candidate_records(MemoryQuery(statuses=[MemoryStatus.ACTIVE,MemoryStatus.COLD]),[],('', '',0),cluster_ids,limit=5)
            for neighbor,sources in siblings:
                if 'cluster' not in sources or neighbor.id in boosted:continue
                self.lifecycle_policy.activate(neighbor,now,.02,direct=False,reason='cluster_sibling')
                await self.repository.save(neighbor);boosted.add(neighbor.id)
                if len(boosted)>=20:break
        edges=await self.repository.edges_for([x.record.id for x in strong],min_weight)
        graph_ids=[]
        for edge in edges:
            for memory_id in (edge.source_id,edge.target_id):
                if memory_id in boosted:continue
                neighbor=await self.repository.get(memory_id)
                if neighbor and neighbor.status in {MemoryStatus.ACTIVE,MemoryStatus.COLD}:
                    self.lifecycle_policy.activate(neighbor,now,.008*edge.weight,direct=False,reason='graph_neighbor')
                    await self.repository.save(neighbor);boosted.add(memory_id);graph_ids.append(memory_id)
            if len(graph_ids)>=12:break
        if graph_ids:
            count=0
            for edge in await self.repository.edges_for(graph_ids,min_weight):
                for memory_id in (edge.source_id,edge.target_id):
                    if memory_id in boosted:continue
                    neighbor=await self.repository.get(memory_id)
                    if neighbor and neighbor.status in {MemoryStatus.ACTIVE,MemoryStatus.COLD}:
                        self.lifecycle_policy.activate(neighbor,now,.002*edge.weight,direct=False,reason='graph_two_hop')
                        await self.repository.save(neighbor);boosted.add(memory_id);count+=1
                if count>=12:break

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
            reasons.append(f"cluster_id={item.cluster.id}")
        reasons.append(f"time={item.time_score:.3f}")
        return reasons
