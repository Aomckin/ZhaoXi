"""Perception api routes with explicit application dependencies."""
from fastapi import APIRouter, HTTPException


def perception_api_router(core, configured, perception, source_runtime):
    router = APIRouter()

    @router.get("/api/perception/inspect")
    async def perception_inspect():
        return perception.diagnostics() if perception else {"enabled": False}


    @router.post("/api/perception/flush")
    async def perception_flush():
        if perception is None:
            raise HTTPException(status_code=503, detail="Perception 未启用")
        return {"batches": await perception.flush(force=True)}


    @router.post("/api/perception/clear-expired")
    async def perception_clear_expired():
        if perception is None:
            raise HTTPException(status_code=503, detail="Perception 未启用")
        return {"deleted": perception.store.clear_expired(configured.perception_observation_ttl_hours)}


    @router.get("/api/perception/recent")
    async def perception_recent():
        if perception is None:
            raise HTTPException(status_code=503, detail="Perception 未启用")
        return {"observations": perception.store.inspect_recent_observations(),
                "snapshots": [x.model_dump(mode="json") for x in perception.store.recent_all_snapshots()],
                "media_payloads_included": False}


    @router.get("/api/perception/sessions")
    async def perception_sessions():
        if perception is None:
            raise HTTPException(status_code=503, detail="Perception 未启用")
        sessions = await core.session_store.list()
        return {"sessions": [{"id": item.id, "updated_at": item.updated_at.isoformat(),
                              "messages": len(item.conversation.messages)}
                             for item in sessions if item.id.count("/") >= 2 and not item.id.startswith("local/")][:30]}


    @router.get("/api/perception/self-events")
    async def perception_self_events():
        if perception is None:
            raise HTTPException(status_code=503, detail="Perception 未启用")
        return {"events": [item.model_dump(mode="json") for item in perception.ledger.recent(20)]}


    @router.post("/api/perception/process-pending")
    async def perception_process_pending():
        if perception is None:
            raise HTTPException(status_code=503, detail="Perception 未启用")
        return {"processed": await perception.process_pending_snapshot()}


    @router.post("/api/perception/clear-ledger")
    async def perception_clear_ledger():
        if perception is None:
            raise HTTPException(status_code=503, detail="Perception 未启用")
        return {"deleted": perception.ledger.clear_expired()}


    @router.post("/api/perception/resolve-last-image")
    async def perception_resolve_last_image():
        if perception is None:
            raise HTTPException(status_code=503, detail="Perception 未启用")
        item = next((x for x in perception.store.recent_observations(30)
                     if any(part.type == "image" for part in x.effective_parts)), None)
        if item is None:
            return {"status": "none"}
        images = await perception._images(item)
        return {"status": perception.images.last_status, "resolved_count": len(images),
                "raw_ref": item.raw_ref}


    @router.get("/api/perception/expression")
    async def perception_expression():
        from zhaoxi.perception.context import ChannelExpressionPolicy
        return {"private": ChannelExpressionPolicy.prompt("private"),
                "group": ChannelExpressionPolicy.prompt("group")}


    @router.get("/api/external-sources")
    async def external_sources():
        return source_runtime.diagnostics() if source_runtime else []


    @router.post("/api/external-sources/{plugin_id}/enable")
    async def enable_external_source(plugin_id: str):
        if source_runtime is None or plugin_id not in source_runtime._state:
            raise HTTPException(status_code=404, detail="Source unavailable")
        await source_runtime.enable(plugin_id)
        return source_runtime.diagnostics()


    @router.post("/api/external-sources/{plugin_id}/disable")
    async def disable_external_source(plugin_id: str):
        if source_runtime is None or plugin_id not in source_runtime._state:
            raise HTTPException(status_code=404, detail="Source unavailable")
        await source_runtime.disable(plugin_id)
        return source_runtime.diagnostics()


    @router.post("/api/external-sources/{plugin_id}/restart")
    async def restart_external_source(plugin_id: str):
        if source_runtime is None or plugin_id not in source_runtime._state:
            raise HTTPException(status_code=404, detail="Source unavailable")
        await source_runtime.restart(plugin_id)
        return source_runtime.diagnostics()


    return router
