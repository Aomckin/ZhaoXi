"""Cluster-first recall, bounded escape candidates and mode-aware reranking."""
from collections import defaultdict
from time import perf_counter
from zhaoxi.memory.embedding import compatible, cosine, embedding_space
from zhaoxi.memory.models import MemorySearchResult, MemoryStatus, RetrievalMode, utc_now


def resolve_mode(query):
    if query.retrieval_mode != RetrievalMode.ASSOCIATIVE:
        return query.retrieval_mode
    if any(x in query.text for x in ("翻一下记忆", "搜索所有", "都有哪些", "都喝过什么", "所有记忆")):
        return RetrievalMode.BROAD_SEARCH
    if query.explicit_recall or any(x in query.text for x in ("记得", "以前", "之前", "上次", "那次", "发生过什么")):
        return RetrievalMode.EXPLICIT_RECALL
    return RetrievalMode.ASSOCIATIVE


def allowed_statuses(query, mode):
    if query.statuses != [MemoryStatus.ACTIVE]:
        return [x for x in query.statuses if x not in {MemoryStatus.FORGOTTEN, MemoryStatus.SUPERSEDED}
                and (mode != RetrievalMode.ASSOCIATIVE or x in {MemoryStatus.ACTIVE,MemoryStatus.COLD})]
    return [MemoryStatus.ACTIVE, MemoryStatus.COLD] if mode == RetrievalMode.ASSOCIATIVE else [
        MemoryStatus.ACTIVE, MemoryStatus.COLD, MemoryStatus.DORMANT, MemoryStatus.ARCHIVED]


def cluster_limits(query, mode, cluster_scores):
    """Only a strong, distinct best cluster relaxes focused recall diversity."""
    limits = {}
    best = cluster_scores[0][0] if cluster_scores else 0
    runner_up = cluster_scores[1][0] if len(cluster_scores) > 1 else 0
    focused = mode == RetrievalMode.EXPLICIT_RECALL and best >= .55 and best - runner_up >= .12
    for rank, (score, cluster) in enumerate(cluster_scores):
        limit = query.per_cluster_limit
        if mode == RetrievalMode.BROAD_SEARCH:
            limit = max(limit, 4)
        elif focused and rank == 0:
            limit = query.limit
        limits[cluster.id] = limit
    return limits, focused


async def retrieve(service, query, activate=True):
    started = perf_counter()
    mode = resolve_mode(query)
    candidate_query = query.model_copy(update={"statuses": allowed_statuses(query, mode)})
    if not candidate_query.statuses:
        service.last_retrieval = {"retrieval_mode": mode.value,"status_filter":[],"candidates":[],"cluster_candidates":[]}
        return []
    if not query.text:
        records = await service.repository.list_records(candidate_query)
        service.last_retrieval = {"retrieval_mode": mode.value,
            "status_filter": [x.value for x in candidate_query.statuses],
            "cluster_candidates": [], "candidate_count": len(records), "excluded": [], "selected": []}
        return [MemorySearchResult(record=r, retrieval_mode=mode, candidate_source=["filter"]) for r in records
                if r.status != MemoryStatus.COLD or mode != RetrievalMode.ASSOCIATIVE]
    now = query.now or utc_now()
    embedding_error = None
    embedding_started = perf_counter()
    try:
        vector = await service.embedding_provider.embed(query.text)
    except (OSError, ValueError) as error:
        # Keep lexical/FTS recall available without comparing incompatible vectors.
        embedding_error = type(error).__name__
        vector = []
    except Exception as error:
        import httpx
        if not isinstance(error, httpx.HTTPError):
            raise
        embedding_error = type(error).__name__
        vector = []
    embedding_ms = (perf_counter() - embedding_started) * 1000
    space = embedding_space(service.embedding_provider)
    clusters = await service.repository.cluster_candidates(query.text, vector, space)
    cluster_scores = []
    for cluster in clusters:
        semantic = cosine(vector, cluster.centroid_embedding) if compatible(service.embedding_provider, cluster) else 0
        text = service._text_overlap(query.text, f"{cluster.topic} {cluster.summary} {' '.join(cluster.tags)} {' '.join(cluster.entities)}")
        entity = max((1.0 for x in cluster.entities if x.casefold() in query.text.casefold()), default=0)
        score = semantic*.65 + text*.25 + entity*.08 + cluster.activation*.01 + cluster.importance*.01
        if max(semantic, text, entity) > .05:
            cluster_scores.append((score, cluster))
    cluster_scores.sort(key=lambda x:x[0],reverse=True)
    cluster_scores = cluster_scores[:5]
    cluster_map = {c.id:c for _,c in cluster_scores}
    cluster_ranks = {c.id:(s,i+1) for i,(s,c) in enumerate(cluster_scores)}
    candidates = await service.repository.candidate_records(candidate_query, vector, space,
        list(cluster_map), limit=100 if mode == RetrievalMode.BROAD_SEARCH else 40)
    candidate_clusters = await service.repository.clusters_for([r.cluster_id for r, _ in candidates if r.cluster_id])
    embeddings = await service.repository.embeddings_for([r.id for r,_ in candidates])
    generation_finished = perf_counter()
    generation_ms = (generation_finished-started)*1000-embedding_ms
    scored, excluded = {}, []
    for record, sources in candidates:
        text = service._text_score(query.text, record)
        embedding = embeddings.get(record.id)
        semantic = cosine(vector, embedding.vector) if embedding and compatible(service.embedding_provider, embedding) else 0
        contextual = text*.6 + semantic*.4
        reason = None
        if max(text,semantic) < .10:
            reason = "insufficient query relevance"
        elif mode == RetrievalMode.ASSOCIATIVE and record.status == MemoryStatus.COLD and contextual < .45:
            reason = "COLD requires high contextual relevance"
        elif mode == RetrievalMode.ASSOCIATIVE and record.kind.value in {"state","intent"} and record.valid_until and record.valid_until < now:
            reason = "expired current state"
        if reason:
            excluded.append({"memory_id":record.id,"status":record.status.value,"candidate_source":sources,"why_excluded":reason})
            continue
        cs, rank = cluster_ranks.get(record.cluster_id, (0,None))
        scored[record.id] = MemorySearchResult(record=record, contextual_relevance=round(contextual,4),
            text_score=text, semantic_score=semantic, time_score=service._time_score(record,now),
            activation_score=record.activation,importance_score=record.importance,cluster=candidate_clusters.get(record.cluster_id),
            cluster_score=cs,cluster_rank=rank,candidate_source=sources,retrieval_mode=mode)
    if scored:
        best_context=max(item.contextual_relevance for item in scored.values())
        floor=max(.12,best_context*.45)
        for memory_id,item in list(scored.items()):
            if item.contextual_relevance<floor:
                excluded.append({'memory_id':memory_id,'why_excluded':'weak relevance relative to best query match',
                                 'candidate_source':item.candidate_source,'why_demoted':'context precision guard'})
                del scored[memory_id]
    # Graph enriches candidates that already passed query/status gating.
    seeds=sorted(scored.values(),key=lambda x:x.contextual_relevance,reverse=True)[:5]
    await service._expand_graph(scored,seeds,candidate_query,cluster_map,now)
    for item in scored.values():
        item.score=round(item.text_score*.47+item.semantic_score*.33+item.cluster_score*.06+item.graph_score*.05+
                         item.time_score*.03+item.activation_score*.03+item.importance_score*.03,4)
        item.why_selected=service._why(item)+["sources="+','.join(item.candidate_source),"mode="+mode.value]
        item.match_reason="; ".join(item.why_selected)
    ranked=sorted(scored.values(),key=lambda x:(x.score,x.record.updated_at),reverse=True)
    counts=defaultdict(int);selected=[]
    limits, focused = cluster_limits(query, mode, cluster_scores)
    default_limit = max(query.per_cluster_limit, 4) if mode == RetrievalMode.BROAD_SEARCH else query.per_cluster_limit
    for item in ranked:
        key=item.record.cluster_id or item.record.id
        if len(selected)>=query.limit or counts[key]>=limits.get(key, default_limit):
            excluded.append({"memory_id":item.record.id,"why_excluded":"result limit" if len(selected)>=query.limit else "cluster diversity",
                             "why_demoted":"bounded context", "candidate_source":item.candidate_source})
            continue
        counts[key]+=1;selected.append(item)
    service.last_retrieval={"retrieval_mode":mode.value,"status_filter":[s.value for s in candidate_query.statuses],
        "cluster_candidates":[{"cluster_id":c.id,"domain":c.domain,"topic":c.topic,"cluster_score":round(s,4),"cluster_rank":i+1,
                               "why_included":"semantic/text/entity cluster match"} for i,(s,c) in enumerate(cluster_scores)],
        "cluster_diversity":{"focused_cluster":next(iter(limits),None) if focused else None,"limits":limits,"default_limit":default_limit},
        "embedding_status":"lexical_fallback" if embedding_error else "available",
        "embedding_error":embedding_error,"query_embedding_ms":round(embedding_ms,3),"candidate_count":len(candidates),"candidate_generation_ms":round(generation_ms,3),
        "rerank_ms":round((perf_counter()-generation_finished)*1000,3),"excluded":excluded,
        "selected":[{"memory_id":x.record.id,"why_included":x.match_reason,"why_promoted":"query relevance", "candidate_source":x.candidate_source} for x in selected]}
    if activate and query.statuses == [MemoryStatus.ACTIVE]:
        await service._activate_selected(selected,query.min_edge_weight,now)
    return selected
