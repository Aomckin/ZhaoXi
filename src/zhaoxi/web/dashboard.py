"""Local authenticated dashboard routes; all writes enter domain services."""
from datetime import UTC, datetime
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, StrictBool
from zhaoxi import __version__
from zhaoxi.internal_activity.control import PresenceSettings, ActivitySettings, ActivityConfig
from zhaoxi.current_cognition.editor import CognitionEditor, ManualEdit

class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_social_write: StrictBool = False
class OverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool

def dashboard_router(core, static_dir, *, desktop_open_callback=None):
    router = APIRouter()
    def activity():
        value = getattr(core,"internal_activity",None)
        if value is None: raise HTTPException(409,"内部活动尚未就绪。")
        return value
    def editor():
        value = getattr(core,"current_cognition",None)
        if value is None: raise HTTPException(409,"近期认知尚未就绪。")
        return CognitionEditor(value)
    def update(section, value, name=None, reset=False):
        try:
            activity().control.update(section,value,name=name,reset=reset)
        except (ValueError, KeyError) as exc:
            raise HTTPException(422,str(exc)) from exc
        except OSError as exc:
            raise HTTPException(503,"保存配置失败，当前生效值未改变。") from exc
        activity().publish_presence()
        return activity().control.snapshot(section) if section != "configs" else activity().control.config(name)
    @router.get("/dashboard",include_in_schema=False)
    async def dashboard():
        return FileResponse(static_dir / "dashboard.html", headers={"Cache-Control":"no-store"})
    @router.post("/api/dashboard/open-desktop")
    async def open_desktop():
        if desktop_open_callback is None:
            raise HTTPException(409, "当前 Core 未连接桌面窗口。")
        desktop_open_callback()
        return {"opened": True}
    @router.get("/api/dashboard/overview")
    async def overview():
        r = getattr(core,"internal_activity",None)
        cognition = getattr(core,"current_cognition",None)
        counts = r._day() if r else {}
        return {"version":__version__,"core":{"healthy":getattr(core,"provider",None) is not None,
            "activity_available":r is not None,"activity_enabled":r.settings.internal_activity_enabled if r else False},
            "presence":r.presence_status() if r else None,"recent_activity":r.history(8)["items"] if r else [],
            "today":{"activities":sum(counts.get(spec.name,0) for spec in r.registry) if r else 0,"resources":r._daily.get("resources",{}) if r else {},
                     "changed":r._daily.get("changed",0) if r else 0,"external_messages":r._daily.get("external_messages",0) if r else 0},
            "cognition":cognition.render_for_desk() if cognition else None,
            "plugins":getattr(getattr(core,"perception",None),"sources",None).diagnostics() if getattr(getattr(core,"perception",None),"sources",None) else []}
    @router.get("/api/presence/status")
    async def presence_status(): return activity().presence_status()
    @router.get("/api/settings/presence")
    async def get_presence(): return activity().control.snapshot("presence")
    @router.put("/api/settings/presence")
    async def put_presence(body:PresenceSettings): return update("presence",body.model_dump(mode="json",exclude_unset=True))
    @router.post("/api/settings/presence/reset")
    async def reset_presence(): return update("presence",{},reset=True)
    @router.get("/api/settings/internal-activity")
    async def get_activity():
        r=activity()
        return {**r.control.snapshot("activity"),"today_used":r._daily.get("resources",{}),"counts":r._day()}
    @router.put("/api/settings/internal-activity")
    async def put_activity(body:ActivitySettings): return update("activity",body.model_dump(mode="json",exclude_unset=True))
    @router.post("/api/settings/internal-activity/reset")
    async def reset_activity(): return update("activity",{},reset=True)
    @router.post("/api/debug/presence/override")
    async def debug_override(body:OverrideRequest):
        r=activity()
        r.control.debug_override = {"active_hold_seconds":10,"semi_active_hold_seconds":20,"heartbeat_interval_seconds":5,"heartbeat_enabled":True,"heartbeat_multipliers":{p:1 for p in r.control.defaults["presence"]["heartbeat_multipliers"]}} if body.enabled else None
        r.control.apply()
        interaction = getattr(getattr(core,"proactive_state",None),"interaction",None)
        if body.enabled and interaction:
            now = datetime.now(UTC)
            interaction.force_debug_state(None, now)
            interaction.interact(now)
        r.publish_presence()
        return r.control.snapshot("presence")
    @router.post("/api/debug/presence/reset")
    async def reset_force():
        state=getattr(core,"proactive_state",None)
        if state is None: raise HTTPException(409,"Presence 尚未就绪。")
        state.interaction.force_debug_state(None,datetime.now(UTC))
        return activity().presence_status()
    @router.get("/api/internal-activity/registry")
    async def registry(): return {"items":activity().registry_status(),"enabled":activity().settings.internal_activity_enabled}
    @router.get("/api/internal-activity/history")
    async def history(limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0)):
        return activity().history(limit,offset)
    @router.post("/api/internal-activity/{name}/run")
    async def run(name:str,body:RunRequest):
        r=activity()
        if name not in r.registry: raise HTTPException(404,"未知活动。")
        receipt=await r.run_manual(name,confirm_social_write=body.confirm_social_write)
        return {"receipt":receipt,"raw":receipt["raw_payload"]}
    @router.put("/api/internal-activity/{name}/config")
    async def config(name:str,body:ActivityConfig):
        if name not in activity().registry: raise HTTPException(404,"未知活动。")
        return update("configs",body.model_dump(mode="json",exclude_unset=True),name=name)
    @router.post("/api/internal-activity/{name}/config/reset")
    async def reset_config(name:str):
        if name not in activity().registry: raise HTTPException(404,"未知活动。")
        return update("configs",{},name=name,reset=True)
    @router.get("/api/current-cognition")
    async def get_cognition(): return editor().service.state().model_dump(mode="json")
    def edit(target,key,body,operation):
        try: return editor().edit(target,key,body,operation)
        except KeyError as exc: raise HTTPException(404,"条目不存在。") from exc
        except ValueError as exc: raise HTTPException(409,str(exc)) from exc
    @router.patch("/api/current-cognition/overview")
    async def overview_edit(body:ManualEdit): return edit("overview",None,body,"edit")
    @router.post("/api/current-cognition/{target}")
    async def add(target:Literal["thread","watch","change"],body:ManualEdit): return edit(target,None,body,"add")
    @router.patch("/api/current-cognition/{target}/{key}")
    async def patch(target:Literal["thread","watch","change"],key:str,body:ManualEdit): return edit(target,key,body,"edit")
    @router.delete("/api/current-cognition/{target}/{key}")
    async def delete(target:Literal["thread","watch","change"],key:str): return edit(target,key,ManualEdit(),"delete")
    @router.post("/api/current-cognition/thread/{key}/fade")
    async def fade(key:str): return edit("thread",key,ManualEdit(),"fade")
    @router.get("/api/current-cognition/revisions")
    async def revisions(limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0)): return editor().service.store.revisions(limit,offset)
    @router.post("/api/current-cognition/revisions/{revision_id}/undo")
    async def undo(revision_id:int):
        try: return editor().undo(revision_id)
        except ValueError as exc: raise HTTPException(409,str(exc)) from exc
    return router
