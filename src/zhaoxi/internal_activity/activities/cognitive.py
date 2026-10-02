"""Bounded gardening and weak-signal digestion; never replay AutoMemory."""
from collections import Counter
from datetime import UTC, datetime, timedelta
import json
from zhaoxi.core.message import Message, Role
from zhaoxi.cognitive_stream.provenance import from_event
from zhaoxi.current_cognition.service import normalize_key, CurrentCognitionPatch
from zhaoxi.current_cognition.maintainer import _parse_patch
from zhaoxi.current_cognition.prompts import MAINTAINER_PROMPT
from zhaoxi.memory.models import MemoryQuery, MemoryStatus, MemoryEdge
from difflib import SequenceMatcher
import re
from zhaoxi.memory.embedding import compatible, cosine
from zhaoxi.memory.candidate_index import lexical_tokens
from zhaoxi.memory.clustering import refresh, organize
from zhaoxi.observability import llm_owner_scope
from ..models import ActivityResult, ActivitySpec, ActivityCategory as Category, CostClass as Cost, PresenceState as Presence

FAST_DIGEST = "fast_digest"
COGNITION_GARDENING = "cognition_gardening"
MEMORY_GARDENING = "memory_gardening"
CLUSTER_GARDENING = "cluster_gardening"
REMINISCENCE = "memory_reminiscence"
STATUSES = [MemoryStatus.ACTIVE, MemoryStatus.COLD, MemoryStatus.DORMANT, MemoryStatus.ARCHIVED]

def fast_events(r):
    stream = getattr(r.agent, "experience_stream", None)
    if stream is None:
        return [], []
    page = stream.events_after(r.state[FAST_DIGEST].get("fast_digest_cursor"), limit=200)
    trusted = [e for e in page if e.actor_role == "OWNER" and e.trust_level in {"TRUSTED", "NORMAL"}
               and e.event_type.value in {"USER_MESSAGE", "EXTERNAL_MESSAGE"}
               and e.metadata.get("dialogue_lane") == "fast_chat" and e.content]
    return page, trusted[:40]

async def fast_due(r, now):
    page, events = fast_events(r)
    r.state[FAST_DIGEST]["pending_fast_signal_count"] = len(events)
    r._save(FAST_DIGEST)
    if page and (len(events) >= getattr(r.settings, "fast_digest_min_signals", 10) or len(page) >= 200):
        return "pending_fast_signals", Cost.LLM_LIGHT.value

async def fast_digest(r, kind):
    page, events = fast_events(r)
    if not page:
        return ActivityResult()
    # A batch without repeated meaningful words needs no model call.
    noise = set(lexical_tokens("哈哈你好早安晚安谢谢好的今天现在刚才觉得这个那个什么怎么嗯嗯"))
    counts = Counter(t for e in events for t in set(lexical_tokens(e.content or "")) - noise)
    repeated = {t for t, n in counts.items() if n >= 3 and len(t) >= 2}
    patch = CurrentCognitionPatch(reason_code="fast_digest_no_trend")
    if repeated:
        provider = r.agent.current_cognition_maintainer.provider
        evidence = [{"id": e.event_id, "text": e.content[:700], "provenance": from_event(e).metadata()} for e in events]
        prompt = MAINTAINER_PROMPT + "\n你正在消化 FAST 闲聊的跨轮弱趋势。只输出 CurrentCognitionPatch JSON。忽略寒暄和单次事实；没有稳定趋势就 NO_CHANGE。不要重新抽取全部长期记忆。"
        state = r.agent.current_cognition.state()
        with llm_owner_scope("fast_digest", "current_cognition"):
            response = await provider.generate([Message(role=Role.SYSTEM, content=prompt),
                Message(role=Role.USER, content=json.dumps({"current_state": state.model_dump(mode="json"),
                    "new_messages": evidence, "repeated_signals": sorted(repeated)[:30]}, ensure_ascii=False))],
                None, max_tokens=1800, temperature=0, response_format={"type": "json_object"})
        patch = _parse_patch(response.content or "")
    # Digest owns a separate cursor. Never move the normal maintainer cursor backwards.
    maintainer = r.agent.current_cognition_maintainer
    async with maintainer._lock:
        service = r.agent.current_cognition
        service.apply(patch, source_by_id={e.event_id: "user" if e.source == "desktop" else "owner_external" for e in events},
            evidence_by_id={e.event_id: e.content for e in events},
            timestamp_by_id={e.event_id: e.occurred_at for e in events},
            provenance_by_id={e.event_id: from_event(e).metadata() for e in events},
            last_message_id=page[-1].event_id, advance_cursor=False, model_call=bool(repeated))
        if service.last_maintenance.get("rejection"):
            raise ValueError("fast_digest_rejected")
    marker = events[-1].event_id if len(events) == 40 else page[-1].event_id
    r.state[FAST_DIGEST].update(fast_digest_cursor=marker, pending_fast_signal_count=0)
    r._save(FAST_DIGEST)
    changed = service.last_maintenance["decision"] == "UPDATE"
    return ActivityResult(status="UPDATE" if changed else "NO_CHANGE", changed=changed,
        summary="Cognition signal" if changed else "没有稳定趋势", evidence_refs=[e.event_id for e in events])

def needs_cognition_gardening(state, now, stream):
    keys = [normalize_key(t.key) for t in state.threads]
    if len(keys) != len(set(keys)) or any(t.status == "resolved" or
        now - t.last_evidence_at >= timedelta(days=3) and t.status == "active" or
        now - t.last_evidence_at >= timedelta(days=7) for t in state.threads):
        return True
    if any(now - x.updated_at >= timedelta(days=3) for x in state.recent_changes):
        return True
    if any(now - x.updated_at >= timedelta(days=7) for x in state.watch_items):
        return True
    items = [*state.threads, *state.recent_changes, *state.watch_items]
    return bool(stream and any(ref.event_id and stream.get(ref.event_id) is None for x in items for ref in x.source_refs))

async def cognition_due(r, now):
    service = getattr(r.agent, "current_cognition", None)
    if service and needs_cognition_gardening(service.state(), now, getattr(r.agent, "experience_stream", None)):
        return "stale_or_duplicate_structure", "local"

async def cognition_gardening(r, kind):
    service = r.agent.current_cognition
    state = service.state()
    before = state.model_dump(mode="json")
    now = datetime.now(UTC)
    service._decay(state, now)
    stream = getattr(r.agent, "experience_stream", None)
    merged = {}
    for thread in state.threads:
        thread.key = normalize_key(thread.key)
        if thread.key in merged:
            target = merged[thread.key]
            target.salience = max(target.salience, thread.salience)
            target.source_refs = list({ref.event_id or ref.message_id: ref for ref in [*target.source_refs, *thread.source_refs]}.values())[-8:]
            target.last_evidence_at = max(target.last_evidence_at, thread.last_evidence_at)
        else:
            merged[thread.key] = thread
    state.threads = list(merged.values())
    for collection in (state.threads, state.recent_changes, state.watch_items):
        for item in collection:
            if stream:
                item.source_refs = [ref for ref in item.source_refs if not ref.event_id or stream.get(ref.event_id)]
        # Remove unsupported watch items; don't manufacture replacement evidence.
    state.watch_items = [x for x in state.watch_items if x.source_refs]
    changed = before != state.model_dump(mode="json")
    if changed:
        state.version += 1
        state.updated_at = now
        state.last_maintenance = {"decision": "UPDATE", "reason": "cognition_gardening", "model_call": False}
        service.store.save(state)
    return ActivityResult(status="UPDATE" if changed else "NO_CHANGE", changed=changed)

async def memory_due(r, now):
    service = r.memory_service
    if service is None:
        return None
    rows = await service.repository.presence_records(since=r._last(MEMORY_GARDENING, "last_success_at"), limit=40)
    return ("recent_memories", "local") if rows else None

async def memory_gardening(r, kind):
    service = r.memory_service
    if service is None:
        return ActivityResult(status="SKIP")
    repository = service.repository
    rows = await repository.presence_records(since=r._last(MEMORY_GARDENING, "last_success_at"), limit=40)
    changes = await service.maintain(limit=40, organize=False)
    audits = []
    for record in rows:
        issues = []
        if not any((record.source_event_id, record.source_ref, record.evidence_reference, record.evidence_memory_ids)):
            issues.append("missing_evidence")
        if record.activation >= .98 and not record.pinned:
            issues.append("overheated")
        # Near duplicates and polarity conflicts remain review candidates.
        vector = (await repository.embeddings_for([record.id])).get(record.id)
        candidates = await repository.candidate_records(MemoryQuery(text=record.content, statuses=STATUSES),
            vector.vector if vector and compatible(service.embedding_provider, vector) else [],
            (vector.embedding_model, vector.embedding_version, vector.embedding_dim) if vector else
                ("local-hash-v1", "1", 256), limit=10)
        related = {}
        for peer, _ in candidates:
            if peer.id == record.id:
                continue
            ratio = SequenceMatcher(None, record.normalized_content, peer.normalized_content).ratio()
            if ratio >= .9 and record.normalized_content != peer.normalized_content:
                related.setdefault("dedup_candidates", []).append(peer.id)
            negated = lambda text: bool(re.search(r"不再|不喜欢|没有|取消|not |never ", text, re.I))
            if ratio >= .6 and set(record.entities) & set(peer.entities) and negated(record.content) != negated(peer.content):
                related.setdefault("contradiction_candidates", []).append(peer.id)
        if related:
            await repository.update_presence_metadata(record.id, related)
            audits.append(record.id)
        edges = await repository.edges_for([record.id])
        if any(edge.relation.value == "contradicts" for edge in edges):
            issues.append("conflict_review")
        if record.importance < .2:
            issues.append("low_value_noise")
        if issues and record.metadata.get("gardening_issues") != issues:
            await repository.update_presence_metadata(record.id, {"gardening_issues": issues})
            audits.append(record.id)
        await repository.update_presence_metadata(record.id, {"presence_memory_gardened_at": datetime.now(UTC).isoformat()})
    return ActivityResult(status="UPDATE" if changes or audits else "NO_CHANGE", changed=bool(changes or audits),
        summary=f"维护 {len(rows)} 条近期记忆，修复/标记 {len(changes) + len(audits)} 条",
        evidence_refs=list(dict.fromkeys([x.id for x in changes] + audits)))

async def cluster_due(r, now):
    service = r.memory_service
    if service is None:
        return None
    rows, clusters = await service.repository.presence_clusters(r._last(CLUSTER_GARDENING, "last_success_at"), limit=10)
    return ("dirty_clusters_or_orphans", "local") if rows or clusters else None

async def cluster_gardening(r, kind):
    service = r.memory_service
    repository = service.repository
    rows, clusters = await repository.presence_clusters(r._last(CLUSTER_GARDENING, "last_success_at"), limit=10)
    refs = []
    # Existing compatible embeddings only; gardening never issues embedding API calls.
    for record in rows:
        embedding = (await repository.embeddings_for([record.id])).get(record.id)
        if embedding and compatible(service.embedding_provider, embedding):
            await organize(service, record, merge=False)
            refs.append(record.id)
        else:
            await repository.update_presence_metadata(record.id, {"cluster_gardening_candidate": "embedding_repair"})
            refs.append(record.id)
        await repository.update_presence_metadata(record.id, {"presence_cluster_gardened_at": datetime.now(UTC).isoformat()})
    for cluster in clusters:
        members = await repository.list_cluster_members(cluster.id)
        members = [m for m in members if m.status not in {MemoryStatus.SUPERSEDED, MemoryStatus.FORGOTTEN}]
        # Bound work on malformed oversized legacy clusters; leave splitting to explicit maintenance.
        if len(members) > service.cluster_max_members * 2:
            cluster.metadata["split_candidate"] = True
            cluster.metadata["presence_cluster_gardened_at"] = datetime.now(UTC).isoformat()
            await repository.save_cluster(cluster)
            refs.append(cluster.id)
            continue
        await refresh(service, cluster, members)
        peers = await repository.cluster_candidates(cluster.summary, cluster.centroid_embedding,
            (cluster.embedding_model, cluster.embedding_version, cluster.embedding_dim), limit=10)
        cluster.metadata["merge_candidates"] = [c.id for c in peers if c.id != cluster.id and
            service._cluster_similarity(cluster, c) >= service.cluster_merge_threshold and
            c.member_count + cluster.member_count <= service.cluster_max_members][:3]
        cluster.metadata["split_candidate"] = bool(len(members) >= service.cluster_max_members or
            len(members) >= 4 and cluster.metadata.get("coherence", 1) < .45)
        cluster.metadata["drift_candidate"] = bool(members and cluster.metadata.get("coherence", 1) < .3)
        cluster.metadata["presence_cluster_gardened_at"] = cluster.updated_at.isoformat()
        await repository.save_cluster(cluster)
        refs.append(cluster.id)
    return ActivityResult(status="UPDATE" if refs else "NO_CHANGE", changed=bool(refs),
                          summary=f"增量整理 {len(refs)} 个记忆/簇", evidence_refs=refs)

async def reminiscence_due(r, now):
    if r.memory_service is None:
        return None
    rows = await r.memory_service.repository.reminiscence_candidates(now,
        cooldown_days=getattr(r.settings, "memory_reminiscence_cooldown_days", 14), limit=1)
    return ("old_meaningful_memory", "local") if rows else None

async def reminiscence(r, kind):
    service = r.memory_service
    if service is None:
        return ActivityResult(status="SKIP")
    now = datetime.now(UTC)
    rows = await service.repository.reminiscence_candidates(now,
        cooldown_days=getattr(r.settings, "memory_reminiscence_cooldown_days", 14), limit=1)
    if not rows:
        return ActivityResult()
    record = rows[0]
    peers = await service.repository.list_records(MemoryQuery(text=record.content, statuses=STATUSES, limit=40))
    candidates = [p for p in peers if p.id != record.id and
                  (set(record.entities) & set(p.entities) or set(record.tags) & set(p.tags))]
    existing = {(edge.source_id, edge.target_id) for edge in await service.repository.edges_for([record.id])}
    new = next((p for p in candidates if (record.id, p.id) not in existing and (p.id, record.id) not in existing), None)
    result = "NO_CHANGE"
    if new:
        await service.repository.save_edge(MemoryEdge(source_id=record.id, target_id=new.id, weight=.3,
            evidence_memory_ids=[record.id, new.id]))
        result = "RELATED_TO"
    await service.repository.update_presence_metadata(record.id, {
        "last_reminisced_at": now.isoformat(),
        "reminiscence_count": int(record.metadata.get("reminiscence_count", 0)) + 1,
        "last_reminiscence_result": result})
    r.state[REMINISCENCE]["last_memory_id"] = record.id
    r.state[REMINISCENCE]["reminiscence_count"] = r.state[REMINISCENCE].get("reminiscence_count", 0) + 1
    return ActivityResult(status="UPDATE" if new else "NO_CHANGE", changed=bool(new),
        summary=result, evidence_refs=[record.id] + ([new.id] if new else []))

def register_cognitive(registry, settings):
    awake = frozenset({Presence.SEMI_ACTIVE, Presence.IDLE})
    definitions = [
        (FAST_DIGEST, Category.COGNITION, Cost.LLM_LIGHT, 40, 30, fast_digest, fast_due, "消化最近的闲聊", ""),
        (COGNITION_GARDENING, Category.COGNITION, Cost.LOCAL_LIGHT, 75, 30, cognition_gardening, cognition_due, "收拾近期状态", ""),
        (MEMORY_GARDENING, Category.MEMORY, Cost.LOCAL_HEAVY, 62, 60, memory_gardening, memory_due, "整理记忆", ""),
        (CLUSTER_GARDENING, Category.MEMORY, Cost.LOCAL_HEAVY, 61, 120, cluster_gardening, cluster_due, "收拾记忆小抽屉", ""),
        (REMINISCENCE, Category.LEISURE, Cost.LOCAL_LIGHT, 20, 240, reminiscence, reminiscence_due, "在翻旧日记", "memory_reminiscence_daily_limit"),
    ]
    for name, category, cost, priority, interval, handler, candidate, label, daily in definitions:
        setting = "current_cognition_gardening_enabled" if name == COGNITION_GARDENING else name + "_enabled"
        registry.register(ActivitySpec(name, category, cost, awake, priority,
            getattr(settings, setting.removesuffix("_enabled") + "_min_interval_minutes", interval), handler, candidate,
            enabled_setting=setting, daily_limit_setting=daily, label=label))
