"""Semantic membership with domain priors; isolated memories stay orphans."""
import math
import re
from zhaoxi.memory.embedding import compatible, cosine, embedding_space
from zhaoxi.memory.models import MemoryCluster, MemoryQuery, MemoryStatus, utc_now

SUBTOPICS = {
    "Zhaoxi开发": {"Runtime": ("runtime","运行时","heartbeat","心跳"), "Memory": ("memory","记忆","聚类","召回"),
        "Current Cognition": ("current cognition","当前认知","living journal"), "Persona": ("persona","人格","角色设定"),
        "QQ": ("qq","napcat"), "LifeHUD": ("lifehud",), "UI": ("界面","ui","前端"), "Tool System": ("工具","tool","mcp")},
    "求职": {"公司 / 面试": ("面试","亚信","丘脑"), "网申": ("网申",), "笔试": ("笔试",),
        "岗位偏好": ("岗位","职位"), "秋招状态": ("秋招",), "简历": ("简历",)}
}


def has_hint(text, hint):
    if hint.isascii():
        return bool(re.search(r"(?<![a-z0-9_])" + re.escape(hint) + r"(?![a-z0-9_])", text))
    return hint in text


def label(service, record):
    domain = service._infer_topic(record)
    text = f"{record.content} {' '.join(record.tags)}".casefold()
    # Labels describe groups; they never override a semantic membership score.
    sub = next((name for name,hints in SUBTOPICS.get(domain,{}).items() if any(has_hint(text, x) for x in hints)), None)
    return domain, sub or (record.tags[0] if record.tags else (record.entities[0] if record.entities else (record.summary or record.content)[:40]))


def domain_prior(left, right):
    """Soft compatibility: very strong semantic matches may cross domains."""
    from zhaoxi.memory.service import MemoryService
    known = MemoryService.TOPIC_HINTS
    if left == right or (left not in known and right not in known):
        return 1.0
    return .6 if left in known and right in known else .8


def centroid(vectors):
    if not vectors:
        return []
    vector=[sum(x)/len(vectors) for x in zip(*vectors)]
    norm=math.sqrt(sum(x*x for x in vector))
    return [x/norm for x in vector] if norm else vector


async def refresh(service, cluster, records):
    embeddings=await service.repository.embeddings_for([r.id for r in records])
    vectors=[e.vector for e in embeddings.values() if compatible(service.embedding_provider,e)]
    cluster.centroid_embedding=centroid(vectors)
    cluster.embedding_model,cluster.embedding_version,cluster.embedding_dim=embedding_space(service.embedding_provider)
    cluster.member_count=len(records)
    cluster.importance=sum(r.importance for r in records)/max(len(records),1)
    cluster.activation=sum(r.activation for r in records)/max(len(records),1)
    # Recompute descriptive labels from members, rather than retaining the first
    # record's domain through unrelated additions or merges.
    from collections import Counter
    labels = [label(service, record) for record in records]
    if labels:
        cluster.domain = Counter(domain for domain, _ in labels).most_common(1)[0][0]
        cluster.topic = Counter(topic for domain, topic in labels if domain == cluster.domain).most_common(1)[0][0]
    cluster.tags=list(dict.fromkeys(t for r in records for t in r.tags))[:30]
    cluster.entities=list(dict.fromkeys(t for r in records for t in r.entities))[:50]
    cluster.metadata["kinds"]=list({r.kind.value for r in records})
    cluster.metadata["coherence"]=round(sum(cosine(v,cluster.centroid_embedding) for v in vectors)/max(len(vectors),1),4)
    cluster.representative_memory_ids=[r.id for r in sorted(records,key=lambda r:r.importance,reverse=True)[:3]]
    cluster.summary="；".join((r.summary or r.content)[:100] for r in records[:3])[:350]
    times=[r.event_at for r in records if r.event_at]
    cluster.time_start=min(times) if times else None;cluster.time_end=max(times) if times else None
    cluster.updated_at=utc_now()
    await service.repository.save_cluster(cluster)


async def organize(service, record, *, merge=True):
    embedding=(await service.repository.embeddings_for([record.id])).get(record.id)
    if not embedding or not compatible(service.embedding_provider,embedding):
        return
    domain,topic=label(service,record)
    clusters=await service.repository.cluster_candidates(record.content,embedding.vector,embedding_space(service.embedding_provider))
    candidates=[(service._cluster_match_score(record,c,embedding.vector),c) for c in clusters if c.member_count<service.cluster_max_members]
    score,cluster=max(candidates,default=(0,None),key=lambda x:x[0])
    members=[]
    if cluster and score>=service.cluster_match_threshold:
        members=await service.repository.list_cluster_members(cluster.id)
        members=[r for r in members if r.id!=record.id and r.status not in {MemoryStatus.FORGOTTEN,MemoryStatus.SUPERSEDED}]
    else:
        cluster=None
        peers=await service.repository.candidate_records(MemoryQuery(text=record.content,statuses=[MemoryStatus.ACTIVE,MemoryStatus.COLD,MemoryStatus.DORMANT,MemoryStatus.ARCHIVED]),embedding.vector,embedding_space(service.embedding_provider),limit=30)
        peers=[p for p,_ in peers if p.id!=record.id and not p.cluster_id]
        vectors=await service.repository.embeddings_for([p.id for p in peers])
        peer_score,peer=max(((cosine(embedding.vector,vectors[p.id].vector)*domain_prior(domain,label(service,p)[0]),p) for p in peers if p.id in vectors and compatible(service.embedding_provider,vectors[p.id])),default=(0,None),key=lambda x:x[0])
        if peer is None or peer_score<max(.42,service.cluster_match_threshold):
            record.metadata["cluster_reason"]="orphan: no sufficiently similar semantic peer"
            record.metadata["domain"]=domain
            await service.repository.save(record)
            return
        cluster=MemoryCluster(topic=topic,domain=domain,metadata={"origin":"semantic_pair"})
        members=[peer];score=peer_score
    await refresh(service,cluster,[*members,record])
    for member in [*members,record]:
        member_score=service._cluster_match_score(member,cluster,(await service.repository.embeddings_for([member.id]))[member.id].vector)
        await service.repository.add_cluster_member(cluster.id,member.id,min(.99,member_score))
        member.cluster_id=cluster.id
        member.metadata.update({"domain":service._infer_topic(member),"cluster_reason":f"semantic membership={member_score:.4f}"})
        await service.repository.save(member)
    for peer in members[:5]:
        from zhaoxi.memory.models import MemoryEdge
        await service.repository.save_edge(MemoryEdge(source_id=record.id,target_id=peer.id,weight=max(.25,score),evidence_memory_ids=[record.id,peer.id]))
    if merge:
        await service._maybe_merge_clusters(cluster)


def plan_groups(service, records, embeddings):
    """Offline greedy split/recluster plan; no live database mutations."""
    groups=[];orphans=[]
    for record in sorted(records,key=lambda r:r.id):
        e=embeddings.get(record.id)
        if not e or not compatible(service.embedding_provider,e):
            orphans.append(record);continue
        # Semantic signal dominates. Domains only supply interpretable labels.
        domain,topic=label(service,record)
        def membership(g):
            semantic=cosine(e.vector,g["centroid"])
            if semantic<.30:return 0.0
            tags=service._set_overlap(set(record.tags),g['tags'])
            entities=service._set_overlap(set(record.entities),g['entities'])
            types=1.0 if record.kind.value in g['kinds'] else 0.0
            prior=1.0 if domain and domain==g['domain'] else 0.0
            score=(semantic*.68+tags*.12+entities*.10+types*.06+prior*.04)*domain_prior(domain,g['domain'])
            known_topics=set(SUBTOPICS.get(domain,{}))
            if domain==g['domain'] and topic in known_topics and g['topic'] in known_topics and topic!=g['topic']:
                score*=.70
            return score
        scores=[(membership(g),g) for g in groups if len(g["members"])<service.cluster_max_members]
        score,group=max(scores,default=(0,None),key=lambda x:x[0])
        if group is None or score<service.cluster_match_threshold:
            groups.append({"domain":domain,"topic":topic,"members":[record],"centroid":e.vector,
                "tags":set(record.tags),"entities":set(record.entities),"kinds":{record.kind.value}})
        else:
            group["members"].append(record)
            group["tags"].update(record.tags);group["entities"].update(record.entities);group["kinds"].add(record.kind.value)
            group["centroid"]=centroid([embeddings[r.id].vector for r in group["members"]])
    stable=[]
    for g in groups:
        if len(g["members"])<2:orphans.extend(g["members"])
        else:
            from collections import Counter
            labels = [label(service, record) for record in g['members']]
            g['domain'] = Counter(domain for domain, _ in labels).most_common(1)[0][0]
            g['topic'] = Counter(topic for domain, topic in labels if domain == g['domain']).most_common(1)[0][0]
            stable.append(g)
    return stable,orphans
