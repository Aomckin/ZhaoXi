"""Memory api routes with explicit application dependencies."""
from fastapi import APIRouter, HTTPException


def memory_api_router(core, configured):
    router = APIRouter()

    @router.get("/api/debug/memory-retrieval")
    async def debug_memory_retrieval(query: str, limit: int = 10, retrieval_mode: str = "ASSOCIATIVE", memory_id: str | None = None):
        if not configured.memory_retrieval_debug_enabled:
            raise HTTPException(status_code=404, detail="Memory Inspector 未启用。")
        service = getattr(core, "memory_service", None)
        if service is None:
            raise HTTPException(status_code=409, detail="Memory 尚未就绪。")
        from zhaoxi.memory.models import MemoryQuery, RetrievalMode
        try: mode=RetrievalMode(retrieval_mode)
        except ValueError: raise HTTPException(status_code=422,detail="Invalid retrieval_mode")
        items = await service.inspect_retrieval(MemoryQuery(text=query[:1000], limit=max(1, min(limit, 30)),retrieval_mode=mode))
        observation=dict(service.last_retrieval)
        if memory_id:
            record=await service.get(memory_id)
            if record:
                selected=next((x for x in observation.get('selected',[]) if x['memory_id']==memory_id),None)
                excluded=next((x for x in observation.get('excluded',[]) if x['memory_id']==memory_id),None)
                observation['requested_memory']={'id':memory_id,'status':record.status.value,'source_event_id':record.source_event_id,
                    'evidence_reference':record.evidence_reference,'source_message_id':record.source_message_id,
                    'activation_history':record.metadata.get('activation_history',[]),'lifecycle_reason':record.metadata.get('lifecycle_reason'),
                    'cluster_reason':record.metadata.get('cluster_reason'),
                    'write_decision':record.metadata.get('decision'),'write_reason':record.metadata.get('reason'),
                    'evidence_refs':record.metadata.get('evidence_refs',[]),'evidence_scope':record.metadata.get('evidence_scope'),'evidence_provenance':record.metadata.get('evidence_provenance',[]),'why':selected or excluded or
                    {'why_excluded':'status filter' if record.status.value not in observation.get('status_filter',[]) else 'outside bounded candidate sources'}}
            else:observation['requested_memory']={'id':memory_id,'why_excluded':'memory does not exist'}
        return {"query": query[:1000], **observation, "candidates": [{
            "content": item["record"]["content"], "final_score": item["score"],
            "contextual_relevance": item["contextual_relevance"],
            "text_score": item["text_score"], "semantic_score": item["semantic_score"],
            "graph_score": item["graph_score"], "time_score": item["time_score"],
            "activation_score": item["activation_score"], "importance_score": item["importance_score"],
            "status": item["record"]["status"], "importance": item["record"]["importance"],
            "activation": item["record"]["activation"], "why_selected": item["why_selected"],
            "source_event_id":item["record"].get("source_event_id"),
            "source_message_id":item["record"].get("source_message_id"),
            "evidence_reference":item["record"].get("evidence_reference"),
            **{key:item["record"].get("metadata",{}).get(key) for key in
               ("decision","reason","evidence_refs","evidence_scope","evidence_provenance","activation_history","lifecycle_reason","cluster_reason")},
            "memory_id":item["record"]["id"],"cluster":item["cluster"],"cluster_score":item["cluster_score"],
            "cluster_rank":item["cluster_rank"],"candidate_source":item["candidate_source"],"retrieval_mode":item["retrieval_mode"],
        } for item in items]}


    @router.get("/api/debug/memory-clusters")
    async def debug_memory_clusters():
        service=getattr(core,"memory_service",None)
        if not service: raise HTTPException(status_code=409,detail="Memory not ready")
        return {"clusters":[c.model_dump(mode='json',exclude={'centroid_embedding'}) for c in await service.repository.list_clusters()],
                "diagnostics":await service.diagnostics()}


    @router.get("/api/debug/database-maintenance")
    async def debug_database_maintenance():
        from zhaoxi.reliability.media import database_metrics, MediaBlobStore
        from pathlib import Path
        from zhaoxi.reliability.sqlite import connect
        paths={'memory':configured.memory_db_path,'experience':configured.experience_db_path,
               'perception':configured.perception_db_path,'session':configured.session_db_path,'archive':configured.archive_db_path}
        stats={name:database_metrics(path) for name,path in paths.items()}
        media=MediaBlobStore(configured.media_directory).stats()
        refs=0
        for name,table,column in [('experience','events','payload'),('perception','observations','payload'),('session','sessions','messages_json')]:
            path=Path(paths[name])
            if not path.exists():continue
            with connect(path.resolve().as_uri()+'?mode=ro',uri=True) as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(table,)).fetchone():
                    refs+=db.execute(f"SELECT COALESCE(SUM((length({column})-length(replace({column},'\"$media\"','')))/8),0) FROM {table}").fetchone()[0]
        media['references']=refs
        media['dedup_ratio']=round(max(0,1-media['media_blobs']/refs),4) if refs else 0
        return {'databases':stats,'media':media,'maintenance':'offline CLI; default dry-run'}


    return router
