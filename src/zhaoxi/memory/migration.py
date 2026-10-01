"""Offline audit/reindex/recluster with SQLite snapshots and cancellation.

Dry runs work exclusively on a snapshot. Applying or restoring requires the
runtime to be stopped; SQLite backup publishes the staged DB transactionally.
"""
import asyncio
import json
import math
import sqlite3
from zhaoxi.reliability.sqlite import connect
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from zhaoxi.memory.clustering import plan_groups, refresh
from zhaoxi.memory.embedding import embedding_space
from zhaoxi.memory.models import MemoryCluster, MemoryQuery, MemoryStatus, utc_now

ACTIONS = ('all','rebuild_memory_embeddings','rebuild_cluster_centroids','rebuild_memory_fts','recluster_memories','rebalance_activation')


def snapshot(source, target):
    source,target=Path(source),Path(target)
    if source.resolve()==target.resolve():raise ValueError('backup target must differ from source')
    target.parent.mkdir(parents=True,exist_ok=True)
    with connect(source.resolve().as_uri()+'?mode=ro',uri=True) as src, connect(target) as dst:
        src.backup(dst)
        if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('backup integrity check failed')
    return target


def restore(source, target):
    source,target=Path(source),Path(target)
    if source.resolve()==target.resolve():raise ValueError('restore source must differ from target')
    with connect(source.resolve().as_uri()+'?mode=ro',uri=True) as src, connect(target) as dst:
        if src.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('invalid restore snapshot')
        src.backup(dst)
    return {'restored':str(target),'backup':str(source)}


def audit(path):
    with connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        columns={r['name'] for r in db.execute('PRAGMA table_info(memories)')}
        heat='activation' if 'activation' in columns else 'relevance'
        total=db.execute('SELECT count(*) FROM memories').fetchone()[0]
        clusters=[dict(r) for r in db.execute('SELECT cluster_id,count(*) AS member_count FROM memories WHERE cluster_id IS NOT NULL GROUP BY cluster_id ORDER BY member_count DESC')]
        histogram=dict(db.execute(f'SELECT CAST({heat}*10 AS INTEGER),count(*) FROM memories GROUP BY CAST({heat}*10 AS INTEGER)'))
        statuses=dict(db.execute('SELECT status,count(*) FROM memories GROUP BY status'))
        duplicates=[dict(r) for r in db.execute('SELECT normalized_content,count(*) AS copies FROM memories GROUP BY normalized_content HAVING count(*)>1')]
        evidence_columns = [name for name in ('source_event_id', 'evidence_reference', 'source_message_id') if name in columns]
        missing = db.execute("SELECT count(*) FROM memories WHERE " +
            (" AND ".join(f"({name} IS NULL OR {name}='')" for name in evidence_columns) or "1")).fetchone()[0]
        embedding_columns = {r['name'] for r in db.execute('PRAGMA table_info(memory_embeddings)')}
        space_columns = [name for name in ('embedding_model', 'embedding_version', 'embedding_dim') if name in embedding_columns]
        space_sql = ','.join(space_columns)
        versions = [dict(r) for r in db.execute(f'SELECT {space_sql},count(*) AS count FROM memory_embeddings GROUP BY {space_sql}')]

        orphans=db.execute('SELECT count(*) FROM memories WHERE cluster_id IS NULL').fetchone()[0]
    return {'total':total,'cluster_distribution':clusters,'activation_histogram':histogram,'by_status':statuses,
            'duplicate_candidates':duplicates,'orphan_memories':orphans,'missing_evidence':missing,'embedding_versions':versions}


async def records_all(repository):
    rows=[];offset=0
    while True:
        batch=await repository.list_records(MemoryQuery(statuses=list(MemoryStatus),limit=100,offset=offset))
        rows.extend(batch)
        if len(batch)<100:break
        offset+=100
    return rows


async def migrate(path, *, action='all', dry_run=True, output_dir=None, embedding_provider=None,
                  cluster_max_members=80, cancel=lambda:False, progress=lambda value:None, embedding_snapshot=None):
    from zhaoxi.memory.service import MemoryService
    from zhaoxi.memory.sqlite import SQLiteMemoryRepository
    if action not in ACTIONS:raise ValueError('unknown memory migration action')
    path=Path(path)
    before=audit(path)
    def check(phase,index=0,total=0):
        if cancel():raise asyncio.CancelledError('migration cancelled before publication')
        progress({'phase':phase,'completed':index,'total':total})
    stamp=datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')
    output=Path(output_dir) if output_dir else path.parent/'memory-migrations'/stamp
    output.mkdir(parents=True,exist_ok=True)
    backups=[]
    if not dry_run:
        for source in (path,path.parent/'archive.db',path.parent/'experience.db'):
            if source.exists():backups.append(str(snapshot(source,output/(source.name+'.bak'))))
    with tempfile.TemporaryDirectory(prefix='zhaoxi-memory-') as directory:
        staged=Path(directory)/'memory.db'
        snapshot(path,staged)
        repo=SQLiteMemoryRepository(staged)
        service=MemoryService(repo,embedding_provider=embedding_provider,cluster_max_members=cluster_max_members)
        records=await records_all(repo)
        active=[r for r in records if r.status not in {MemoryStatus.FORGOTTEN,MemoryStatus.SUPERSEDED}]
        reused = 0
        if embedding_snapshot:
            from zhaoxi.memory.embedding import compatible
            # Read the seed without initializing or modifying it. Preserve all
            # current records, edges and lifecycle data from the business DB.
            from zhaoxi.memory.models import MemoryEmbedding
            with connect(Path(embedding_snapshot).resolve().as_uri()+'?mode=ro',uri=True) as seed:
                seed.row_factory = sqlite3.Row
                for record in active:
                    row = seed.execute('SELECT * FROM memory_embeddings WHERE memory_id=?',(record.id,)).fetchone()
                    if row is None: continue
                    vector = json.loads(row['vector_json'])
                    embedding = MemoryEmbedding(memory_id=record.id,embedding_model=row['embedding_model'],
                        embedding_version=row['embedding_version'],embedding_dim=row['embedding_dim'],
                        embedding_hash=row['embedding_hash'],vector=vector)
                    if (compatible(service.embedding_provider,embedding)
                            and embedding.embedding_hash==service.embedding_provider.content_hash(record.content)
                            and any(vector) and all(math.isfinite(v) for v in vector)):
                        await repo.save_embedding(embedding)
                        reused += 1
        rebuild=action in {'all','rebuild_memory_embeddings'}
        if rebuild:
            batch_embed = getattr(service.embedding_provider, 'embed_many', None)
            if batch_embed is None:
                for i,r in enumerate(active):
                    check('embedding',i,len(active))
                    await service._ensure_embedding(r)
            else:
                from zhaoxi.memory.embedding import compatible
                from zhaoxi.memory.models import MemoryEmbedding
                existing = await repo.embeddings_for([r.id for r in active])
                pending = [r for r in active if not (r.id in existing
                    and compatible(service.embedding_provider, existing[r.id])
                    and existing[r.id].embedding_hash == service.embedding_provider.content_hash(r.content))]
                model, version, dimensions = embedding_space(service.embedding_provider)
                from contextlib import AsyncExitStack
                from copy import copy
                from zhaoxi.memory.embedding import SemanticEmbeddingProvider
                async with AsyncExitStack() as stack:
                    if isinstance(service.embedding_provider, SemanticEmbeddingProvider) and service.embedding_provider.client is None:
                        import httpx
                        pooled = copy(service.embedding_provider)
                        pooled.client = await stack.enter_async_context(httpx.AsyncClient())
                        batch_embed = pooled.embed_many
                    for i in range(0, len(pending), 10):
                        check('embedding',i,len(pending))
                        batch = pending[i:i+10]
                        vectors = await batch_embed([r.content for r in batch])
                        if len(vectors) != len(batch):
                            raise ValueError('embedding batch size mismatch')
                        for r, vector in zip(batch, vectors):
                            await repo.save_embedding(MemoryEmbedding(memory_id=r.id, embedding_model=model,
                                embedding_hash=service.embedding_provider.content_hash(r.content), vector=vector,
                                embedding_version=version, embedding_dim=dimensions))

        embeddings=await repo.embeddings_for([r.id for r in active])
        # Existing vectors also need their SQL postings populated.
        for i,e in enumerate(embeddings.values()):
            check('embedding_index',i,len(embeddings));await repo.save_embedding(e)
        groups,orphans=plan_groups(service,active,embeddings)
        plan={'groups':[{'domain':g['domain'],'topic':g['topic'],'member_ids':[r.id for r in g['members']],
                        'old_cluster_ids':list({r.cluster_id for r in g['members'] if r.cluster_id})} for g in groups],
              'orphan_ids':[r.id for r in orphans]}
        plan['splits']={cid:sum(cid in g['old_cluster_ids'] for g in plan['groups']) for cid in {r.cluster_id for r in active if r.cluster_id}}
        plan['merges']=sum(len(g['old_cluster_ids'])>1 for g in plan['groups'])
        if action in {'all','recluster_memories'}:
            check('recluster')
            with repo._connect() as db:
                db.execute('DELETE FROM memory_cluster_members')
                db.execute('DELETE FROM memory_clusters')
                if repo.fts5_available:db.execute('DELETE FROM clusters_fts')
                db.execute("DELETE FROM embedding_features WHERE owner='cluster'")
                db.execute('UPDATE memories SET cluster_id=NULL')
            from zhaoxi.memory.clustering import label
            for r in records:
                r.cluster_id = None
            for r in active:
                domain, _ = label(service, r)
                r.metadata['domain'] = domain
                r.metadata['cluster_reason'] = 'orphan: no sufficiently similar semantic peer in migration'
                await repo.save(r)
            for i,g in enumerate(groups):
                check('recluster',i,len(groups))
                cluster=MemoryCluster(domain=g['domain'],topic=g['topic'],metadata={'origin':'migration_semantic'})
                await refresh(service,cluster,g['members'])
                for r in g['members']:
                    score=service._cluster_match_score(r,cluster,embeddings[r.id].vector)
                    await repo.add_cluster_member(cluster.id,r.id,min(.99,score))
                    r.cluster_id=cluster.id;r.metadata['cluster_reason']=f'migration semantic score={score:.4f}'
                    await repo.save(r)
        elif action=='rebuild_cluster_centroids':
            for i,cluster in enumerate(await repo.list_clusters()):
                check('centroid',i)
                members=await repo.list_cluster_members(cluster.id)
                await refresh(service,cluster,[r for r in members if r.status not in {MemoryStatus.FORGOTTEN,MemoryStatus.SUPERSEDED}])
        if action in {'all','rebalance_activation'}:
            now=utc_now()
            for i,r in enumerate(active):
                check('rebalance',i,len(active))
                age=max((now-(r.accessed_at or r.created_at)).total_seconds()/86400,0)
                before_heat=r.activation
                r.activation=round(min(.9,(.30+.30*r.importance+.10*min(math.log1p(r.access_count)/5,1))*math.exp(-age/45)),4)
                service.lifecycle_policy._history(r,now,'migration_rebalance',before_heat)
                r.metadata['activation_decayed_at']=now.isoformat()
                r.status=service.lifecycle_policy.classify(r,now)
                await repo.save(r)
        if action in {'all','rebalance_activation'}:
            for cluster in await repo.list_clusters():
                members = await repo.list_cluster_members(cluster.id)
                await refresh(service, cluster, [r for r in members if r.status not in {MemoryStatus.FORGOTTEN,MemoryStatus.SUPERSEDED}])
        if action in {'all','rebuild_memory_fts','recluster_memories'}:
            check('fts')
            with repo._connect() as db:
                if repo.fts5_available:db.execute('DELETE FROM memories_fts')
                db.execute('DELETE FROM memory_entity_terms')
                db.execute("INSERT OR REPLACE INTO memory_runtime VALUES ('fts_format','3')")
                for r in records:repo._sync_fts(db,r)
            for cluster in await repo.list_clusters():await repo.save_cluster(cluster)
        check('report')
        after=audit(staged)
        report={'publication_status':'planned' if dry_run else 'staged','dry_run':dry_run,'action':action,'before':before,'after':after,'plan':plan,'backups':backups,
                'embedding_space':embedding_space(service.embedding_provider),'reused_seed_embeddings':reused,'evidence_policy':'unknown legacy sources remain unknown'}
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        check('publish')
        if not dry_run:
            restore(staged,path)
            report['publication_status']='published'
            (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        report['report_path']=str(output/'report.json')
        return report


async def split_oversized_clusters(service):
    """Background split only when an oversized cluster has poor coherence."""
    for cluster in await service.repository.list_clusters():
        if not cluster.active or cluster.member_count<=service.cluster_max_members:continue
        members=await service.repository.list_cluster_members(cluster.id)
        members=[r for r in members if r.status not in {MemoryStatus.FORGOTTEN,MemoryStatus.SUPERSEDED}]
        embeddings=await service.repository.embeddings_for([r.id for r in members])
        from zhaoxi.memory.embedding import cosine
        coherence=sum(cosine(e.vector,cluster.centroid_embedding) for e in embeddings.values())/max(len(embeddings),1)
        if coherence>=.85:continue
        groups,orphans=plan_groups(service,members,embeddings)
        # Build replacements before retiring the old index.
        for g in groups:
            replacement=MemoryCluster(domain=g['domain'],topic=g['topic'],metadata={'split_from':cluster.id})
            await refresh(service,replacement,g['members'])
            for r in g['members']:
                await service.repository.add_cluster_member(replacement.id,r.id,service._cluster_match_score(r,replacement,embeddings[r.id].vector))
        for r in orphans:
            with service.repository._connect() as db:
                db.execute('DELETE FROM memory_cluster_members WHERE memory_id=?',(r.id,))
            r.cluster_id = None
            r.metadata['cluster_reason'] = 'orphan after oversized cluster split'
            await service.repository.save(r)
        cluster.active=False;cluster.metadata['split_reason']=f'size={len(members)},coherence={coherence:.4f}'
        await service.repository.save_cluster(cluster)
        await service._increment_runtime('cluster_split_count')
