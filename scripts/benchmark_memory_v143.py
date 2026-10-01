"""Compare the exact pre-v1.4.3 search against a migrated snapshot.

Labels are developer-selected fixed IDs, pending user review. Raw content stays in the private output;
public reports contain IDs and metrics only. This is a spot-check, not full truth.
"""
import argparse
import asyncio
import json
import subprocess
import tempfile
import types
from pathlib import Path
from zhaoxi.memory.migration import migrate, snapshot
from zhaoxi.memory.models import MemoryQuery, MemoryStatus, RetrievalMode
from zhaoxi.memory.service import MemoryService
from zhaoxi.memory.sqlite import SQLiteMemoryRepository

LABELS = [
    {'query':'朝汐 Runtime','expected':['dc6597e7d76441a09232c2fc38353710'],'domain':'Zhaoxi开发'},
    {'query':'亚信面试','expected':['9c10cd3517e84b31817834df7961bc99','389d71aac75d4b8b9a100a49ad616905','c17fbcbea1c64c65ae62fcee48140314'],'domain':'求职'},
    {'query':'丘脑智能面试','expected':['307fda1864354745b875d95fbbe87620'],'domain':'求职'},
    {'query':'LifeHUD 饮食','expected':['6506d462fe8f4e299d7174bbb45cbd70','9586f0bbf7654f2f8c856638cb5a653b','d21ed845bc4f4ac9bfdd2e2fd1b87f0a','65b9e3beaddd48ebbc13ea52a103d248'],'domain':'LifeHUD'},
    {'query':'舞萌骑行','expected':['ec66b091c8f3411b909d0cb433091e00','b48c5e82084c4751b3bd0995ffdc8276'],'domain':'舞萌'},
    {'query':'喝酒 酒量','expected':['4ca2e971a0124c4a85af278ddd5e3c82','87095b03f5834ad18724baab82a1f506'],'domain':'饮酒'},
    {'query':'寝室冰箱','expected':['b2e9737fae314d568561268b0428b825','c4d38e6d77c1428099a1a8fa2051b41e'],'domain':'寝室'},
    {'query':'秋招状态','expected':['05280b6af6ef4428a544f3fd42287b00','35e478d8009f477d9e9cd46db19dbf1c'],'domain':'求职'},
    {'query':'角色设定图','expected':['31bf8c648b204c68b217ce760d6bb53d','79c750f958a249f69ed1fe9898dbe5a8'],'domain':'Persona'},
    {'query':'QQ 接入','expected':['3a89940cd298462480d5ad221402c4d9','ebfbfde5afc1434c8b2e01e868d5fd63','0978896fcefb4a52a7c2cb4ab51b3913','1e45f5f0a9474ddb827a1817a81feaa1'],'domain':'QQ'}]


def metrics(ids, label, k):
    expected=set(label['expected']);hits=[i for i,x in enumerate(ids) if x in expected]
    forbidden=set(label.get('forbidden',[]))
    return {'recall_at_k':len(hits)/len(expected),'precision_at_k':len(hits)/k,'returned_precision':len(hits)/max(len(ids),1),
            'mrr':1/(hits[0]+1) if hits else 0,'forbidden_hits':len(set(ids)&forbidden)}


async def run(path, output, k=6, baseline_ref='HEAD', labels=None, embedding_provider=None, after_snapshot=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    labels=labels or LABELS
    all_expected={x for l in labels for x in l['expected']}
    # Drinking and dorm-room labels share one event; it is relevant to both.
    shared_drinking={'c4d38e6d77c1428099a1a8fa2051b41e'}
    labels=[{**l,'forbidden':l.get('forbidden',sorted(all_expected-set(l['expected'])-(shared_drinking if '喝酒' in l['query'] else set())))} for l in labels]
    baseline_commit=subprocess.check_output(['git','rev-parse',baseline_ref],encoding='utf-8').strip()
    old_source=subprocess.check_output(['git','show',baseline_commit+':src/zhaoxi/memory/service.py'],encoding='utf-8')
    old_embedding=subprocess.check_output(['git','show',baseline_commit+':src/zhaoxi/memory/embedding.py'],encoding='utf-8')
    module=types.ModuleType('memory_baseline');exec(compile(old_source,'<baseline-memory>','exec'),module.__dict__)
    emodule=types.ModuleType('embedding_baseline');exec(compile(old_embedding,'<baseline-embedding>','exec'),emodule.__dict__)
    module.cosine=emodule.cosine
    with tempfile.TemporaryDirectory(prefix='zhaoxi-benchmark-') as directory:
        old=Path(directory)/'before.db';new=Path(directory)/'after.db'
        snapshot(path,old);snapshot(after_snapshot or path,new)
        old_repo=SQLiteMemoryRepository(old)
        original_list=old_repo.list_records
        async def legacy_list(query):
            if not query.text:return await original_list(query)
            records=[];offset=0
            while offset<max(query.limit*200,10000):
                batch=await original_list(query.model_copy(update={'text':'','limit':100,'offset':offset}))
                records.extend(batch);offset+=100
                if len(batch)<100:break
            return records
        old_repo.list_records=legacy_list
        async def legacy_edges(ids,min_weight=0):
            if not ids:return []
            marks=','.join('?' for _ in ids)
            with old_repo._connect() as db:
                rows=db.execute(f'SELECT * FROM memory_edges WHERE (source_id IN ({marks}) OR target_id IN ({marks})) AND weight>=?',(*ids,*ids,min_weight)).fetchall()
            return [old_repo._edge_from_row(r) for r in rows]
        old_repo.edges_for=legacy_edges
        baseline=module.MemoryService(old_repo)
        report=await migrate(new,dry_run=False,output_dir=output/'migration',embedding_provider=embedding_provider)
        snapshot(new,output/'after.db')
        current=MemoryService(SQLiteMemoryRepository(new),embedding_provider=embedding_provider)
        rows=[]
        for label in labels:
            before=await baseline.search(MemoryQuery(text=label['query'],limit=k),activate=False)
            after=await current.search(MemoryQuery(text=label['query'],limit=k,retrieval_mode=RetrievalMode.EXPLICIT_RECALL),activate=False)
            b=[r.record.id for r in before];a=[r.record.id for r in after]
            async def cluster_coverage(repo):
                expected_records = [await repo.get(memory_id) for memory_id in label['expected']]
                clustered = [r for r in expected_records if r and r.cluster_id]
                return {'expected_clustered_count': len(clustered),
                        'expected_orphan_count': len(expected_records)-len(clustered),
                        'cluster_expected_coverage': len(clustered)/len(expected_records)}
            def cluster_metrics(results):
                grouped=[x for x in results if x.cluster]
                def matches(x):
                    return label['domain'].casefold() in {str(x.cluster.domain or '').casefold(), x.cluster.topic.casefold()}
                return {'cluster_hit_rate':int(any(x.record.id in label['expected'] and matches(x) for x in grouped)),
                        'wrong_cluster_rate':sum(not matches(x) for x in grouped)/len(grouped) if grouped else 0}
            rows.append({'query':label['query'],'label':label,'before_ids':b,'after_ids':a,
                'before_metrics':{**metrics(b,label,k),**cluster_metrics(before),**(await cluster_coverage(old_repo))},'after_metrics':{**metrics(a,label,k),**cluster_metrics(after),**(await cluster_coverage(current.repository))},
                'candidate_generation_ms':current.last_retrieval.get('candidate_generation_ms'),
                'query_embedding_ms':current.last_retrieval.get('query_embedding_ms'),
                'rerank_ms':current.last_retrieval.get('rerank_ms'),
                'before_top_k':[{'id':r.record.id,'content':r.record.content,'cluster':r.cluster.topic if r.cluster else None} for r in before],
                'after_top_k':[{'id':r.record.id,'content':r.record.content,'cluster':r.cluster.topic if r.cluster else None} for r in after]})
        summary={side:{metric:sum(row[side+'_metrics'][metric] for row in rows)/len(rows)
                       for metric in ('recall_at_k','precision_at_k','returned_precision','mrr','forbidden_hits','cluster_hit_rate','wrong_cluster_rate','cluster_expected_coverage')} for side in ('before','after')}
        result={'baseline_ref':baseline_ref,'baseline_commit':baseline_commit,'k':k,'memory_count':report['before']['total'],'embedding_space':report['embedding_space'],'queries':rows,'summary':summary,
            'scope':'Developer-selected fixed-ID spot checks pending user review; other relevant memories are unlabelled, not necessarily distractors',
            'metric_definitions':{'precision_at_k':'labelled relevant hits / K; returned_precision uses the actual returned count',
                'cluster_hit_rate':'at least one returned labelled relevant memory has an actual cluster matching the expected domain',
                'wrong_cluster_rate':'fraction of returned clustered memories outside the expected domain; orphans excluded',
                'cluster_expected_coverage':'fraction of labelled relevant memories that have an active cluster, independent of retrieval'},
            'migration_summary':{key:report['after'][key] for key in ('cluster_distribution','activation_histogram','by_status','orphan_memories')}}
        (output/'benchmark.private.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        public={**result,'queries':[{k:v for k,v in row.items() if k not in {'before_top_k','after_top_k'}} for row in rows]}
        (output/'benchmark.json').write_text(json.dumps(public,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'summary':summary,'memory_count':result['memory_count'],'output':str(output)},ensure_ascii=False))
        return public


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--db',default='.zhaoxi/memory.db');parser.add_argument('--output',default='.zhaoxi/memory-v143-benchmark')
    parser.add_argument('--baseline-ref',default='HEAD');parser.add_argument('--labels')
    parser.add_argument('--after-snapshot',help='Reuse a previously migrated local after.db; compatible vectors are not sent again')
    parser.add_argument('--semantic',action='store_true',help='Use configured semantic provider on the new snapshot only')
    args=parser.parse_args()
    labels=json.loads(Path(args.labels).read_text(encoding='utf-8')) if args.labels else None
    provider=None
    if args.semantic:
        from zhaoxi.config.settings import Settings
        from zhaoxi.memory.embedding import provider_from_settings, LocalHashEmbeddingProvider
        provider=provider_from_settings(Settings())
        if isinstance(provider,LocalHashEmbeddingProvider):
            parser.error('--semantic requires a configured semantic service')
    asyncio.run(run(args.db,args.output,baseline_ref=args.baseline_ref,labels=labels,embedding_provider=provider,after_snapshot=args.after_snapshot))
