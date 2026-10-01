"""Indexed candidate generation. Python only reranks bounded candidate sets.

Signed dimension postings provide approximate semantic escape candidates without
loading every vector. Exact cosine is evaluated only after this SQL shortlist.
"""
import asyncio
import json
import re
from zhaoxi.memory.models import MemoryEmbedding, MemoryStatus


def lexical_tokens(text):
    words = re.findall(r"[a-z0-9_]+", text.casefold())
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        words.extend(run[i:i+2] for i in range(max(1, len(run)-1)))
    return sorted(set(words))


def fts_text(text):
    return " ".join(lexical_tokens(text))


def fts_match(text):
    return " OR ".join('"' + x.replace('"', '""') + '"' for x in lexical_tokens(text)[:64])


def sync_features(db, owner, owner_id, vector, space):
    db.execute("DELETE FROM embedding_features WHERE owner=? AND owner_id=?", (owner, owner_id))
    # Keep strongest dimensions; indexing work is confined to writes/reindex.
    strongest = sorted(enumerate(vector), key=lambda x: abs(x[1]), reverse=True)[:64]
    db.executemany("INSERT INTO embedding_features VALUES (?,?,?,?,?,?,?,?)",
        [(owner, owner_id, *space, i, 1 if v > 0 else -1, abs(v)) for i, v in strongest if v])


class CandidateIndex:
    @staticmethod
    def _filters(query, alias="m"):
        clauses, args = [], []
        if query.statuses:
            clauses.append(f"{alias}.status IN ({','.join('?' for _ in query.statuses)})")
            args += [x.value for x in query.statuses]
        clauses.append(f"{alias}.status NOT IN ('forgotten','superseded')")
        if query.kind:
            clauses.append(f"{alias}.kind=?"); args.append(query.kind.value)
        if query.source_type:
            clauses.append(f"{alias}.source_type=?"); args.append(query.source_type.value)
        for tag in query.tags:
            clauses.append(f"EXISTS (SELECT 1 FROM json_each({alias}.tags_json) WHERE lower(value)=?)")
            args.append(tag.casefold())
        return " AND ".join(clauses), args

    def _semantic_ids(self, db, owner, vector, space, limit, query=None):
        dims = [(i, v) for i, v in sorted(enumerate(vector), key=lambda x: abs(x[1]), reverse=True)[:16] if v]
        if not dims:
            return []
        values = ','.join('(?,?,?)' for _ in dims)
        args = [x for i, v in dims for x in (i, 1 if v > 0 else -1, abs(v))]
        join, filter_sql, filter_args = "", "", []
        if owner == 'cluster':
            join = " JOIN memory_clusters c ON c.id=f.owner_id"
            filter_sql = " AND c.active=1"
        elif query is not None:
            filters, filter_args = self._filters(query)
            join = " JOIN memories m INDEXED BY idx_memories_candidate_filter ON m.id=f.owner_id"
            filter_sql = " AND " + filters
        rows = db.execute(f"WITH q(dim,sign,value) AS (VALUES {values}) "
            "SELECT f.owner_id, sum(f.weight*q.value) AS score FROM q CROSS JOIN embedding_features f "
            "INDEXED BY idx_embedding_features_covering "
            "ON f.dimension=q.dim AND f.sign=q.sign" + join +
            " WHERE f.owner=? AND f.model=? AND f.version=? AND f.dim=?" + filter_sql +
            " GROUP BY f.owner_id ORDER BY score DESC LIMIT ?", (*args, owner, *space, *filter_args, limit)).fetchall()
        return [r[0] for r in rows]

    async def cluster_candidates(self, text, vector, space, limit=20):
        return await asyncio.to_thread(self._cluster_candidates, text, vector, space, limit)

    def _cluster_candidates(self, text, vector, space, limit):
        with self._connect() as db:
            ids = self._semantic_ids(db, 'cluster', vector, space, limit)
            match = fts_match(text)
            if self.fts5_available and match:
                ids += [r[0] for r in db.execute("SELECT cluster_id FROM clusters_fts WHERE clusters_fts MATCH ? ORDER BY rank LIMIT ?", (match, limit))]
            if not ids:
                return []
            rows = db.execute(f"SELECT * FROM memory_clusters WHERE active=1 AND id IN ({','.join('?' for _ in ids)})", ids).fetchall()
        return [self._cluster_from_row(r) for r in rows]

    async def candidate_records(self, query, vector, space, cluster_ids=(), limit=60):
        return await asyncio.to_thread(self._candidate_records, query, vector, space, cluster_ids, limit)

    def _candidate_records(self, query, vector, space, cluster_ids, limit):
        filters, args = self._filters(query)
        sources = {}
        # Allocate one bounded budget across selected clusters, rather than
        # giving every cluster the whole budget. Global channels keep reserves.
        escape_limit = max(5, limit // 2)
        cluster_limit = max(2, limit // max(2 * len(cluster_ids), 1))
        with self._connect() as db:
            def add(name, sql, parameters):
                for row in db.execute(sql, parameters):
                    sources.setdefault(row[0], []).append(name)
            if cluster_ids:
                for cid in cluster_ids:
                    add('cluster', f"SELECT m.id FROM memories m WHERE {filters} AND m.cluster_id=? ORDER BY m.activation DESC,m.updated_at DESC LIMIT ?", (*args,cid,cluster_limit))
            match = fts_match(query.text)
            if self.fts5_available and match:
                add('fts', f"SELECT m.id FROM memories_fts JOIN memories m ON m.id=memories_fts.memory_id WHERE memories_fts MATCH ? AND {filters} ORDER BY rank LIMIT ?", (match,*args,escape_limit))
            ready=db.execute("SELECT value FROM memory_runtime WHERE key='fts_format'").fetchone()
            if query.text and (not self.fts5_available or not ready or ready[0]!='3'):
                # FTS-unavailable fallback stays SQL bounded; never loads the full pool.
                terms = lexical_tokens(query.text)[:12]
                if terms:
                    clause = ' OR '.join('m.content LIKE ?' for _ in terms)
                    add('fts_fallback', f"SELECT m.id FROM memories m WHERE {filters} AND ({clause}) LIMIT ?", (*args,*['%'+x+'%' for x in terms],escape_limit))
            semantic_ids = self._semantic_ids(db, 'memory', vector, space, escape_limit, query)
            if semantic_ids:
                marks = ','.join('?' for _ in semantic_ids)
                add('semantic', f"SELECT m.id FROM memories m WHERE {filters} AND m.id IN ({marks})", (*args,*semantic_ids))
            tokens = lexical_tokens(query.text)
            if tokens:
                marks = ','.join('?' for _ in tokens)
                add('entity', f"SELECT DISTINCT m.id FROM memory_entity_terms t JOIN memories m ON m.id=t.memory_id WHERE {filters} AND t.term IN ({marks}) LIMIT ?", (*args,*tokens,min(escape_limit,10)))
            add('recent', f"SELECT m.id FROM memories m WHERE {filters} AND m.status='active' ORDER BY m.activation DESC,m.created_at DESC LIMIT ?", (*args, min(limit,8)))
            if not sources:
                return []
            ids = list(sources)
            rows = db.execute(f"SELECT * FROM memories WHERE id IN ({','.join('?' for _ in ids)})", ids).fetchall()
        return [(self._from_row(r), sources[r['id']] + ([] if 'cluster' in sources[r['id']] else ['escape'])) for r in rows]

    async def embeddings_for(self, ids):
        return await asyncio.to_thread(self._embeddings_for, ids)

    def _embeddings_for(self, ids):
        if not ids:
            return {}
        with self._connect() as db:
            rows = db.execute(f"SELECT * FROM memory_embeddings WHERE memory_id IN ({','.join('?' for _ in ids)})", ids).fetchall()
        return {r['memory_id']: MemoryEmbedding(memory_id=r['memory_id'], embedding_model=r['embedding_model'],
            embedding_version=r['embedding_version'], embedding_dim=r['embedding_dim'],
            embedding_hash=r['embedding_hash'], vector=json.loads(r['vector_json']), updated_at=r['updated_at']) for r in rows}

    async def clusters_for(self, ids):
        return await asyncio.to_thread(self._clusters_for, list(dict.fromkeys(ids)))

    def _clusters_for(self, ids):
        if not ids:
            return {}
        with self._connect() as db:
            rows = db.execute(f"SELECT * FROM memory_clusters WHERE active=1 AND id IN ({','.join('?' for _ in ids)})", ids).fetchall()
        return {r['id']: self._cluster_from_row(r) for r in rows}
