"""Probe the configured semantic embedding service using synthetic text only."""
import argparse
import asyncio
import json
from pathlib import Path
from time import perf_counter
from zhaoxi.config.settings import Settings
from zhaoxi.memory.embedding import LocalHashEmbeddingProvider, cosine, embedding_space, provider_from_settings

async def probe(output):
    provider = provider_from_settings(Settings())
    if isinstance(provider, LocalHashEmbeddingProvider):
        raise ValueError('Configure semantic URL, model and dimensions before probing')
    start = perf_counter()
    texts = ['下一周要去参加公司的招聘面试。', '近期计划参加求职面谈。', '今天午餐吃了番茄鸡蛋面。']
    vectors = [await provider.embed(text) for text in texts]
    report = {'embedding_space': embedding_space(provider), 'dimensions': [len(v) for v in vectors],
        'duration_ms': round((perf_counter()-start)*1000, 2),
        'paraphrase_similarity': round(cosine(vectors[0],vectors[1]),4),
        'unrelated_similarity': round(cosine(vectors[0],vectors[2]),4),
        'scope': 'Synthetic text only; no database writes. Similarity ordering is a smoke check, not quality certification.'}
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    return report

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default='.zhaoxi/memory-v143-semantic-probe.json')
    args=parser.parse_args()
    asyncio.run(probe(args.output))
