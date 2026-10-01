"""Evaluate new retrieval against frozen historical results with reviewed labels.

No API calls or business DB writes. Private results stay under .zhaoxi.
Reviewed pooled labels are not exhaustive or independent human gold labels.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from zhaoxi.memory.embedding import LocalHashEmbeddingProvider
from zhaoxi.memory.models import MemoryQuery, RetrievalMode
from zhaoxi.memory.service import MemoryService
from zhaoxi.memory.sqlite import SQLiteMemoryRepository
from benchmark_memory_v143 import metrics


async def run(args):
    baseline_path=Path(args.baseline)
    baseline=json.loads(baseline_path.read_text(encoding='utf-8'))
    labels_path=Path(args.labels)
    labels=json.loads(labels_path.read_text(encoding='utf-8'))
    cache=json.loads(Path(args.vectors).read_text(encoding='utf-8'))
    class Cache:
        model,version,dimensions=baseline['embedding_space']
        content_hash=staticmethod(LocalHashEmbeddingProvider.content_hash)
        async def embed(self,text):return cache[text]
    service=MemoryService(SQLiteMemoryRepository(args.snapshot),embedding_provider=Cache())
    old_rows={row['query']:row for row in baseline['queries']}
    rows=[]
    for label in labels:
        old=old_rows[label['query']]
        before_ids=old['before_ids']
        results=await service.search(MemoryQuery(text=label['query'],limit=baseline['k'],retrieval_mode=RetrievalMode.EXPLICIT_RECALL),activate=False)
        after_ids=[x.record.id for x in results]
        reviewed_pool=set(label['reviewed_pool'])
        unreviewed=[x.record.id for x in results if x.record.id not in reviewed_pool and x.record.id not in label['expected']]
        rows.append({'query':label['query'],'criterion':label['criterion'],'before_ids':before_ids,'after_ids':after_ids,
            'before':metrics(before_ids,label,baseline['k']),'after':metrics(after_ids,label,baseline['k']),
            'legacy_before':metrics(before_ids,old['label'],baseline['k']),'legacy_after':metrics(after_ids,old['label'],baseline['k']),
            'unreviewed_ids':unreviewed,'timings':{k:service.last_retrieval[k] for k in ('candidate_count','candidate_generation_ms','rerank_ms')},
            'after_top_k':[{'id':x.record.id,'content':x.record.content,'score':x.score} for x in results],
            'before_top_k':old['before_top_k']})
    def summary(prefix):
        return {metric:sum(row[prefix][metric] for row in rows)/len(rows) for metric in rows[0][prefix]}
    before,after=summary('before'),summary('after')
    gate={key:after[key]+1e-9>=before[key] for key in ('recall_at_k','precision_at_k','mrr')}
    gate['forbidden_hits']=after['forbidden_hits']<=before['forbidden_hits']
    gate['review_coverage']=not any(row['unreviewed_ids'] for row in rows)
    result={'baseline_commit':baseline['baseline_commit'],'memory_count':baseline['memory_count'],'k':baseline['k'],
        'baseline_report_sha256':hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
        'labels_sha256':hashlib.sha256(labels_path.read_bytes()).hexdigest(),
        'review_scope':'Development-agent content review of both pooled result sets; not independent human or exhaustive corpus gold.',
        'summary':{'before':before,'after':after},'original_fixed_ids':{'before':summary('legacy_before'),'after':summary('legacy_after')},
        'gates':gate,'passed':all(gate.values()),'queries':rows}
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    (output/'acceptance.private.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    result['queries']=[{k:v for k,v in row.items() if k not in {'before_top_k','after_top_k'}} for row in rows]
    (output/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('summary','original_fixed_ids','gates','passed')},ensure_ascii=False,indent=2))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',default='.zhaoxi/memory-v143-semantic-acceptance/benchmark.private.json')
    parser.add_argument('--snapshot',default='.zhaoxi/memory-v143-semantic-acceptance/after.db')
    parser.add_argument('--labels',default='.zhaoxi/memory-v143-reviewed-labels.json')
    parser.add_argument('--vectors',default='.zhaoxi/memory-v143-query-vectors.json')
    parser.add_argument('--output',default='.zhaoxi/memory-v143-reviewed-acceptance')
    args=parser.parse_args()
    result=asyncio.run(run(args))
    if not result["passed"]:
        parser.exit(1,"Reviewed acceptance gates did not pass; inspect acceptance.json.\n")
