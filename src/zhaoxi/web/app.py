"""FastAPI application for the local Zhaoxi interaction shell."""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, RedirectResponse
from zhaoxi.tools.manifest import group_inventory, inventory_summary
from zhaoxi.tools.filesystem_access import load_filesystem_access
from zhaoxi.tools.router import safe_resolve_tool_context

from zhaoxi.cli import build_agent
from zhaoxi import __version__
from zhaoxi.config.settings import Settings
from zhaoxi.errors import ZhaoxiError
from zhaoxi.interfaces.setup import StartupUnavailableAgent
from zhaoxi.reflection.models import ReflectionKind, ReflectionRecord
from zhaoxi.reliability import provider_budget_scope
from zhaoxi.reliability.startup import effective_settings_snapshot, startup_diagnostics
from zhaoxi.web.adapter import WebInterfaceAdapter, WebResult
from zhaoxi.web.events import EventBroadcaster
from zhaoxi.voice.policy import SpeechAction, SpeechContext, SpeechPolicy

# Retain request/response imports here for existing app module callers.
from .schemas import (
    ChatRequest,
    ThinkingRequest,
    RegenerateRequest,
    ReplyRenderedRequest,
    ToolControlRequest,
    ToolCapabilityRequest,
    InterfaceSettingsRequest,
    FilesystemAccessRequest,
    EmojiControlRequest,
    EmojiTraceAckRequest,
    RecentContextControlRequest,
    InternalActivityDebugRequest,
    DecisionDebugRequest,
    PresenceDebugRequest,
    EmojiMetadataRequest,
    EmojiCreateRequest,
    EmojiPendingRequest,
    EmojiAnalyzeRequest,
    ChatResponse,
    VoiceConfirmRequest,
    VoiceSpeakRequest,
)
from .settings_api import (
    settings_api_router,
    _load_interface_settings,
    _apply_request_timeout,
    _apply_force_fast_chat,
)
from .perception_api import perception_api_router
from .emoji_api import emoji_api_router
from .memory_api import memory_api_router
from .runtime import build_external_runtime, web_lifespan

logger = logging.getLogger("WEB")


def _response(result: WebResult) -> ChatResponse:
    return ChatResponse(
        content=result.content,
        activity=result.activity,
        permission=result.permission,
        request_id=result.request_id,
        trace_id=result.trace_id,
        status=result.status,
        timestamp=result.timestamp,
        message_id=result.message_id,
        output_messages=result.output_messages or [],
    )


def _safe_reflection(record: ReflectionRecord) -> dict[str, Any]:
    """Expose conclusions and citation ids, never raw evidence or model metadata."""
    return {
        "reflection_id": record.reflection_id,
        "kind": record.kind.value,
        "period": record.period.model_dump(mode="json"),
        "status": record.status.value,
        "revision": record.revision,
        "summary": record.summary,
        "sections": [section.model_dump(mode="json") for section in record.sections],
        "uncertainties": record.uncertainties,
        "evidence_count": len(record.evidence),
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }


def create_app(
    *,
    agent=None,
    settings: Settings | None = None,
    api_token: str | None = None,
    voice_runtime=None,
    now_provider=None,
    restart_callback: Callable[[], bool] | None = None,
    desktop_open_callback: Callable[[], None] | None = None,
) -> FastAPI:
    configured = settings or Settings()
    if agent is not None:
        core = agent
    else:
        try:
            core = build_agent(configured)
        except ZhaoxiError as exc:
            core = StartupUnavailableAgent(startup_diagnostics(configured), str(exc))
    adapter = WebInterfaceAdapter(core)

    def delivered(result: WebResult) -> ChatResponse:
        if result.request_id and result.message_id:
            receipt = adapter.gateway.render_receipts.setdefault(
                result.request_id, {"message_id": result.message_id}
            )
            receipt.setdefault("response_sent_at", datetime.now(UTC).isoformat())
            while len(adapter.gateway.render_receipts) > 100:
                adapter.gateway.render_receipts.popitem(last=False)
        return _response(result)
    core_started_at = datetime.now(UTC)
    events = EventBroadcaster()
    adapter.gateway.event_sink = events.publish_nowait
    static_dir = Path(__file__).with_name("static")
    speech_policy = SpeechPolicy()
    perception, source_runtime = build_external_runtime(configured, core)
    current_time = now_provider or (lambda: datetime.now().astimezone())
    interface_settings_path = Path(configured.interface_settings_path)
    filesystem_access_path = Path(configured.filesystem_access_path)
    interface_settings_value = _load_interface_settings(interface_settings_path)
    _apply_request_timeout(
        core,
        enabled=interface_settings_value.long_wait_enabled,
        default_seconds=configured.request_timeout_seconds,
    )
    _apply_force_fast_chat(core, enabled=interface_settings_value.force_fast_chat)

    def voice_policy(*, text: str, explicit: bool, permission_pending: bool = False):
        now = current_time()
        now_utc = now.astimezone(UTC) if now.tzinfo is not None else now.replace(tzinfo=UTC)
        state = getattr(core, "proactive_state", None)
        quiet = bool(state and state.quiet_until and state.quiet_until > now_utc)
        hour = now.hour
        start = configured.proactive_night_start_hour
        end = configured.proactive_night_end_hour
        night = start <= hour < end if start < end else hour >= start or hour < end
        return speech_policy.decide(SpeechContext(
            voice_enabled=voice_runtime is not None,
            auto_speak=configured.voice_auto_speak,
            explicit_user_action=explicit,
            response_from_voice=not explicit,
            quiet=quiet,
            night=night,
            recording=bool(voice_runtime and voice_runtime.status.value == "recording"),
            permission_pending=permission_pending,
            text_length=len(text),
        ))


    supervisor, lifespan = web_lifespan(core, configured, adapter, events, voice_runtime, perception, source_runtime)
    app = FastAPI(title="Zhaoxi Local Shell", docs_url="/api/docs", lifespan=lifespan)

    from .local_access import local_browser_request
    dashboard_token = secrets.token_urlsafe(32)

    if api_token:
        @app.middleware("http")
        async def require_local_token(request: Request, call_next):
            if request.url.path.startswith("/api/") and request.url.path != "/api/bootstrap":
                supplied = request.headers.get("X-Zhaoxi-Token") or request.cookies.get(
                    "zhaoxi_session", ""
                )
                desktop_authorized = secrets.compare_digest(supplied, api_token)
                browser_authorized = (
                    not request.headers.get("X-Zhaoxi-Token")
                    and secrets.compare_digest(request.cookies.get("zhaoxi_dashboard_session", ""), dashboard_token)
                    and local_browser_request(request)
                )
                if not (desktop_authorized or browser_authorized):
                    return JSONResponse(status_code=401, content={"detail": "本地管理会话无效，请刷新管理面板。"})
            return await call_next(request)

    from fastapi.staticfiles import StaticFiles

    mimetypes.add_type("image/webp", ".webp")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.include_router(settings_api_router(core, configured, events))
    app.include_router(perception_api_router(core, configured, perception, source_runtime))
    app.include_router(emoji_api_router(core, configured, adapter, delivered))
    app.include_router(memory_api_router(core, configured))
    from .dashboard import dashboard_router
    app.include_router(dashboard_router(core, static_dir, desktop_open_callback=desktop_open_callback))
    from .decision_learning import decision_learning_router
    app.include_router(decision_learning_router(core))

    @app.middleware("http")
    async def desktop_entry_guard(request: Request, call_next):
        import posixpath
        normalized_path = posixpath.normpath(request.url.path.replace("\\", "/")).lower().rstrip(" .")
        desktop_authorized = bool(api_token and secrets.compare_digest(request.cookies.get("zhaoxi_session", ""), api_token))
        browser_authorized = (
            secrets.compare_digest(request.cookies.get("zhaoxi_dashboard_session", ""), dashboard_token)
            and local_browser_request(request)
        )
        if normalized_path == "/dashboard":
            if not local_browser_request(request):
                return JSONResponse(status_code=403, content={"detail": "管理面板仅允许本机浏览器访问。"})
            response = await call_next(request)
            response.set_cookie("zhaoxi_dashboard_session", dashboard_token, httponly=True,
                                samesite="strict", path="/")
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Cache-Control"] = "no-store"
            return response
        if normalized_path == "/" and not desktop_authorized and not configured.dev_browser_ui:
            return RedirectResponse("/dashboard", status_code=303)
        engineering = normalized_path in {"/static/dashboard.html", "/static/engineering.html"}
        if engineering and browser_authorized:
            return await call_next(request)
        if normalized_path.startswith("/static/") and normalized_path.endswith(".html") and not configured.dev_browser_ui:
            if not desktop_authorized:
                return JSONResponse(status_code=403, content={"detail": "请从桌面或托盘打开朝汐；浏览器管理页面位于 /dashboard。"})
        return await call_next(request)

    @app.get("/desktop-entry", include_in_schema=False)
    async def desktop_entry(request: Request):
        from fastapi.responses import RedirectResponse
        supplied = request.query_params.get("token", "")
        if not api_token or not secrets.compare_digest(supplied, api_token):
            raise HTTPException(status_code=403, detail="Desktop session required")
        response = RedirectResponse("/", status_code=303)
        response.set_cookie("zhaoxi_session", api_token, httponly=True, samesite="strict", path="/")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(static_dir / "index.html", headers={"Cache-Control": "no-store"})

    @app.post("/api/bootstrap", include_in_schema=False)
    async def bootstrap(request: Request):
        if not api_token:
            return {"status": "not_required"}
        supplied = request.headers.get("X-Zhaoxi-Token", "")
        if not secrets.compare_digest(supplied, api_token):
            raise HTTPException(status_code=401, detail="本地 Desktop 启动令牌无效。")
        response = JSONResponse({"status": "ready"})
        response.set_cookie(
            "zhaoxi_session",
            api_token,
            httponly=True,
            secure=False,
            samesite="strict",
            path="/",
        )
        return response

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "version": __version__}

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        return FileResponse(static_dir / "zhaoxi.ico", media_type="image/x-icon")


    @app.post("/api/proactive/active/poke")
    async def poke():
        worker = getattr(core, "proactive_worker", None)
        if worker is None:
            raise HTTPException(status_code=503, detail="Beat 尚未启用")
        delivery = await worker.poke()
        if delivery:
            await events.publish({"type": "proactive", "delivery": delivery.model_dump(mode="json", exclude={"relevant_payload"})})
        return {"delivered": delivery is not None, "trace": worker.heartbeat.state.interaction.beat_loop.last_trace}

    @app.get("/api/proactive/active/inspect")
    async def active_inspect():
        state = getattr(core, "proactive_state", None)
        beat = getattr(getattr(state, "interaction", None), "beat_loop", None)
        if not beat:
            return {"enabled": False}
        now = datetime.now(UTC)
        return {"enabled": True, "current_state": str(state.interaction.refresh(now)),
                "session": beat.diagnostics(now), "recent_beats": list(beat.trace_history),
                "desktop_suppression": state.interaction._resolve_interruptibility(now).value,
                "last_model_decision": beat.last_model_decision.model_dump() if beat.last_model_decision else None}

    @app.get("/api/desktop/activity/inspect")
    async def desktop_activity_inspect():
        state = getattr(core, "proactive_state", None)
        activity = getattr(getattr(state, "interaction", None), "desktop_activity", None)
        return activity.inspect() if activity else {"enabled": False}

    @app.get("/api/diagnostics")
    async def diagnostics():
        """Return a bounded, content-free local runtime snapshot."""
        backup_manager = getattr(core, "backup_manager", None)
        memory_service = getattr(core, "memory_service", None)
        package_statuses = []
        instances = getattr(core, "tool_package_instances", {})
        for package_record in getattr(core, "tool_packages", []):
            current = dict(package_record)
            package = instances.get(current.get("id"))
            status = getattr(package, "status", None)
            if status is not None:
                current.update(status())
            package_statuses.append(current)
        return {
            "status": "ok",
            "version": __version__,
            "core_started_at": core_started_at.isoformat(),
            "effective_settings": effective_settings_snapshot(configured),
            "metrics": adapter.gateway.metrics.snapshot(),
            "presence": (core.proactive_state.interaction.diagnostics(datetime.now(UTC))
                         if getattr(core, "proactive_state", None) else None),
            "presence_activity": core.internal_activity.public_status() if getattr(core, "internal_activity", None) else None,
            "sensor_health": getattr(getattr(core, "proactive_heartbeat", None), "sensor_health", {}),
            "active": (core.proactive_state.interaction.beat_loop.diagnostics(datetime.now(UTC))
                if getattr(core, "proactive_state", None) and core.proactive_state.interaction.beat_loop else None),
            "desktop_activity": (core.proactive_state.interaction.desktop_activity.diagnostics()
                if getattr(core, "proactive_state", None) and core.proactive_state.interaction.desktop_activity
                else {"enabled": False}),
            "components": {
                "planner": getattr(core, "planner", None) is not None,
                "workflow": getattr(core, "workflow", None) is not None,
                "proactive": getattr(core, "proactive", None) is not None,
                "reflection": getattr(core, "reflection", None) is not None,
                "voice": voice_runtime is not None,
                "background_tasks": supervisor.active_count,
            },
            "archive": (
                core.archive.status()
                if getattr(core, "archive", None) is not None
                else {"enabled": False}
            ),
            "memory": await memory_service.diagnostics() if memory_service is not None else None,
            "tool_packages": package_statuses,
            "tool_package_errors": getattr(core, "tool_package_errors", []),
            "tool_router": getattr(core, "last_tool_diagnostics", None),
            "tool_inventory": tool_snapshot()["summary"] if getattr(core, "registry", None) is not None else None,
            "startup": getattr(core, "startup_diagnostics", None),
            "storage": backup_manager.health() if backup_manager is not None else {},
            "perception": perception.diagnostics() if perception else {"enabled": False},
            "external_sources": source_runtime.diagnostics() if source_runtime else [],
        }


    @app.get("/api/capabilities")
    async def capabilities():
        """Describe installed capabilities without exposing schemas or user data."""
        catalog = getattr(core, "capability_catalog", None)
        registry = getattr(core, "registry", None)
        if catalog is not None and registry is None:
            return catalog
        return {
            **(catalog or {}),
            "status": "ready",
            "tools": [
                {**tool, "description": tool["summary"]}
                for tool in (registry.manifest() if registry is not None else [])
            ],
            "workflows": (catalog or {}).get("workflows", []),
            "packages": (catalog or {}).get("packages", []),
            "examples": (catalog or {}).get("examples", []),
        }

    def tool_snapshot():
        registry = getattr(core, "registry", None)
        if registry is None:
            raise HTTPException(status_code=409, detail="Tool Registry 尚未就绪。")
        state = getattr(core, "_tool_discovery_state", None)
        schemas = state.schemas(registry) if state else safe_resolve_tool_context(
            "", [], registry, mode=getattr(core, "tool_router_mode", "dynamic")
        ).schemas
        manifest = registry.manifest([s["function"]["name"] for s in schemas])
        return {"tools": manifest, "groups": group_inventory(manifest), "summary": inventory_summary(manifest),
                "filesystem_access": {
                    **load_filesystem_access(filesystem_access_path),
                    "restart_required_after_change": True,
                },
                "diagnostics": getattr(core, "last_tool_diagnostics", None)}

    @app.get("/api/debug/runtime")
    async def debug_runtime():
        return {**(getattr(core, "last_action_trace", {}) or {}),
                "live_action_trace": events.action_trace_snapshot(),
                "maintenance": adapter.gateway.maintenance_queue().diagnostics(),
                "render_receipts": dict(adapter.gateway.render_receipts)}


    @app.get("/api/debug/tools")
    async def debug_tools():
        return tool_snapshot()

    def recent_context_snapshot():
        builder = getattr(core, "context_builder", None)
        if builder is None:
            raise HTTPException(status_code=409, detail="Context Builder 尚未就绪。")
        agenda = getattr(core, "agenda", None)
        cognition = getattr(core, "current_cognition", None)
        return {
            "agenda_enabled": bool(getattr(builder, "agenda_context_enabled", False)),
            "final_snapshots": getattr(builder, "last_recent_context", {}),
            "agenda": agenda.diagnostics() if agenda is not None else None,
            "current_cognition": cognition.diagnostics() if cognition is not None else None,
        }

    @app.get("/api/debug/cognitive-stream")
    async def debug_cognitive_stream(channel: str | None = None, actor: str | None = None,
                                     session: str | None = None, limit: int = 50):
        stream = getattr(core, "experience_stream", None)
        if stream is None:
            return {"enabled": False}
        limit = max(1, min(50, limit))
        events = (stream.query_by_channel(channel, limit) if channel else
                  stream.query_by_actor(actor, limit) if actor else
                  stream.query_by_session(session, limit) if session else stream.recent(limit))
        retriever = getattr(core, "attention_retriever", None)
        marker = getattr(getattr(core, "current_cognition", None), "state", lambda: None)()
        cursor = marker.last_processed_message_id if marker else None
        pending = stream.events_after(cursor, limit=200)
        return {**stream.stats(), "recent_events": [item.model_dump(mode="json") for item in events],
                "pending_cognition_events": sum(item.actor_role == "OWNER" and
                    item.event_type.value in {"USER_MESSAGE", "EXTERNAL_MESSAGE"} for item in pending),
                "last_attention_event_ids": retriever.last_result if retriever else [],
                "last_cross_channel_event_ids": retriever.last_cross_channel_result if retriever else [],
                "legacy_session_fallback_count": getattr(getattr(core, "context_builder", None),
                    "legacy_session_fallback_count", 0),
                "interaction_ledger_fallback_count": 0,
                "ingestion_errors": getattr(getattr(core, "cognitive_ingress", None), "errors", 0)}

    @app.get("/api/debug/cognitive-stream/turn")
    async def debug_cognitive_turn(turn_id: str):
        stream = getattr(core, "experience_stream", None)
        if stream is None:
            raise HTTPException(status_code=409, detail="Experience Stream 尚未就绪。")
        events = stream.query_by_turn(turn_id)
        return {"turn_id": turn_id, "events": [item.model_dump(mode="json") for item in reversed(events)]}

    @app.get("/api/debug/cognitive-stream/reply-chain")
    async def debug_cognitive_reply_chain(event_id: str):
        stream = getattr(core, "experience_stream", None)
        if stream is None:
            raise HTTPException(status_code=409, detail="Experience Stream 尚未就绪。")
        trigger = stream.get(event_id)
        replies = stream.query_by_reply_to(event_id)
        return {"trigger": trigger.model_dump(mode="json") if trigger else None,
                "replies": [item.model_dump(mode="json") for item in reversed(replies)]}

    @app.post("/api/debug/cognitive-stream/simulate-concurrent")
    async def debug_cognitive_simulate_concurrent():
        import asyncio
        from zhaoxi.cognitive_stream.models import CognitiveEvent, CognitiveEventType
        from zhaoxi.cognitive_stream.turn import CognitiveTurnContext, current_turn, reset_current_turn, set_current_turn
        async def probe(channel: str) -> dict:
            trigger = CognitiveEvent(event_type=CognitiveEventType.USER_MESSAGE,
                                     source=channel, channel=channel, actor_role="OWNER")
            token = set_current_turn(CognitiveTurnContext(
                trigger_event=trigger, output_channel=channel, reply_target=channel,
                images=(channel,)))
            try:
                await asyncio.sleep(0)
                active = current_turn()
                return {"channel": channel, "isolated": bool(active and
                    active.trigger_event.event_id == trigger.event_id and
                    active.output_channel == channel and active.reply_target == channel and
                    active.images == (channel,))}
            finally:
                reset_current_turn(token)
        results = await asyncio.gather(probe("desktop"), probe("external"))
        return {"passed": all(item["isolated"] for item in results), "results": results}

    @app.get("/api/debug/cognitive-stream/unit")
    async def debug_cognitive_unit(unit_id: str):
        stream = getattr(core, "experience_stream", None)
        unit = stream.resolve_timeline_unit(unit_id) if stream else None
        if unit is None:
            raise HTTPException(status_code=404, detail="Timeline Unit 不存在。")
        return unit

    @app.get("/api/debug/cognitive-stream/social-trace")
    async def debug_social_trace(reference: str | None = None, statement_id: str | None = None,
                                 query: str | None = None, group_id: str | None = None,
                                 source_plugin: str | None = None, since: str | None = None,
                                 until: str | None = None, offset: int = 0,
                                 text_offset: int = 0, limit: int = 8, max_chars: int = 6000):
        from zhaoxi.tools.builtin.social_context import ReadSocialContextInput
        from zhaoxi.cognitive_stream.social_trace import SocialTraceReader
        from pydantic import ValidationError
        stream=getattr(core,"experience_stream",None)
        if stream is None:raise HTTPException(status_code=409,detail="ExperienceStream 尚未就绪。")
        try:
            args=ReadSocialContextInput(reference=reference,statement_id=statement_id,
                query=query,group_id=group_id,source_plugin=source_plugin,since=since,until=until,
                offset=offset,text_offset=text_offset,limit=limit,max_chars=max_chars)
        except ValidationError:
            raise HTTPException(status_code=422,detail="回查参数无效；引用与搜索条件分开使用，时间须含时区。")
        reader=SocialTraceReader(stream, configured.perception_db_path)
        page={"offset":args.offset,"text_offset":args.text_offset,"limit":args.limit,"max_chars":args.max_chars}
        if args.reference:
            return reader.read(args.reference,statement_id=args.statement_id,**page)
        return reader.search(query=args.query,group_id=args.group_id,source_plugin=args.source_plugin,
                             since=args.since,until=args.until,**page)

    @app.get("/api/debug/provenance")
    async def debug_provenance():
        builder = getattr(core, "context_builder", None)
        data = getattr(builder, "last_cognitive_context", {})
        return {"items":data.get("provenance_items", []),
                "legacy_shadow":data.get("legacy_shadow", []),
                "rendered":data.get("provenance_rendered", [])}

    @app.get("/api/debug/cognitive-stream/context")
    async def debug_cognitive_context():
        from zhaoxi.cognitive_stream.turn import active_turns
        builder = getattr(core, "context_builder", None)
        return {"last_rendered": getattr(builder, "last_cognitive_context", {}),
                "active_turns": active_turns()}

    @app.get("/api/debug/cognitive-stream/session")
    async def debug_cognitive_session(session: str = "local"):
        projector = getattr(core, "session_projector", None)
        if projector is None:
            return {"session_id": session, "recent_events": []}
        view = projector.project(session)
        return {"session_id": view.session_id, "channel_metadata": view.channel_metadata,
                "recent_events": [item.model_dump(mode="json") for item in view.recent_events]}

    @app.get("/api/debug/cognitive-stream/attention")
    async def debug_cognitive_attention(query: str, session: str = "local"):
        retriever = getattr(core, "attention_retriever", None)
        if retriever is None:
            return {"events": []}
        context = retriever.retrieve(query, session_id=session)
        return {"events": [item.model_dump(mode="json") for item in context.events],
                "rendered": context.render()}

    @app.get("/api/debug/recent-context")
    async def debug_recent_context():
        return recent_context_snapshot()

    @app.get("/api/debug/decision")
    async def debug_decision():
        if getattr(core, "decision_mode", "legacy") == "agency":
            awareness = getattr(core, "decision_awareness", None)
            if awareness is None:
                raise HTTPException(status_code=409, detail="Decision Awareness 尚未就绪。")
            executor = getattr(core, "tool_executor", None)
            return {**awareness.diagnostics(),
                    "guard_events": list(getattr(executor, "recent_decision_guard_events", [])),
                    "reply_protocol": getattr(core, "last_reply_protocol", None)}
        service = getattr(core, "decision_service", None)
        if service is None:
            raise HTTPException(status_code=409, detail="Decision Layer 尚未就绪。")
        return {"decision_mode": "legacy", **service.diagnostics()}

    @app.post("/api/debug/decision")
    async def debug_evaluate_decision(body: DecisionDebugRequest):
        if getattr(core, "decision_mode", "legacy") == "agency":
            raise HTTPException(status_code=409, detail="Agency 模式从正常回复读取判断记录；不运行额外 Decision 模型。")
        service = getattr(core, "decision_service", None)
        if service is None:
            raise HTTPException(status_code=409, detail="Decision Layer 尚未就绪。")
        from zhaoxi.decision import DecisionService
        from zhaoxi.decision.models import DecisionLevel
        probe = DecisionService(service.provider, rule_directory=service.rules.directory,
            data_directory=service.recorder.directory, agenda=service.agenda,
            current_cognition=service.current_cognition, memory_retriever=service.memory_retriever,
            tool_catalog=service.tool_catalog, timezone=str(service.timezone))
        result = await probe.evaluate(body.message, planner_requested=True,
            forced_level=DecisionLevel(body.forced_level) if body.forced_level else None,
            record=False)
        return {"result": result.model_dump(mode="json") if result else None,
                "context": probe.last_context.model_dump(mode="json") if probe.last_context else None}

    @app.get("/api/debug/internal-activity")
    async def debug_internal_activity():
        activity = getattr(core, "internal_activity", None)
        if activity is None:
            raise HTTPException(status_code=409, detail="Internal Activity 尚未就绪。")
        return activity.diagnostics()

    @app.post("/api/debug/presence")
    async def debug_presence(body: PresenceDebugRequest):
        state = getattr(core, "proactive_state", None)
        if state is None:
            raise HTTPException(status_code=409, detail="Presence 尚未就绪。")
        from zhaoxi.proactive.interaction import InteractionState

        now = datetime.now(UTC)
        state.interaction.force_debug_state(InteractionState(body.state) if body.state else None, now)
        if getattr(core, "internal_activity", None):
            core.internal_activity.publish_presence()
        return state.interaction.diagnostics(now)

    @app.post("/api/debug/internal-activity")
    async def run_debug_internal_activity(body: InternalActivityDebugRequest):
        activity = getattr(core, "internal_activity", None)
        if activity is None:
            raise HTTPException(status_code=409, detail="Internal Activity 尚未就绪。")
        if body.activity != "tick" and body.activity not in activity.registry:
            raise HTTPException(status_code=409, detail="该活动尚未启用 Presence 2.0。")
        if body.activity != "tick":
            receipt = await activity.run_manual(body.activity, confirm_social_write=body.confirm_social_write)
            return {**activity.diagnostics(), "receipts": [receipt], "receipt": receipt}
        deliveries = await activity.run_tick(force=None,
            confirm_social_write=body.confirm_social_write, manual=True)
        for delivery in deliveries:
            await events.publish({"type": "proactive", "delivery": delivery.model_dump(mode="json", exclude={"relevant_payload"})})
        return {**activity.diagnostics(), "receipts": activity.tick_receipts, "receipt": activity.tick_receipts[-1] if activity.tick_receipts else None}

    @app.get("/api/debug/budget-context")
    async def debug_budget_context():
        policy = configured.request_budget_policy
        return {
            "configuration": {
                "base_budget": policy.base_budget,
                "extension_1_limit": policy.extension_1_limit,
                "extension_2_limit": policy.extension_2_limit,
                "hard_limit": policy.hard_limit,
                "finalization_reserve": policy.finalization_reserve,
                "warning_ratio": policy.warning_ratio,
            },
            "last_request": getattr(core, "last_budget_snapshot", None),
        }

    @app.get("/api/recent-context")
    async def recent_context_board():
        """Public desk view; each context source can fail independently."""
        result = {"agenda": [], "current_cognition": None, "errors": {}}
        if getattr(core, "internal_activity", None):
            result["presence"] = core.internal_activity.public_status()
        agenda = getattr(core, "agenda", None)
        if agenda is not None:
            try:
                items = [item.model_dump(mode="json") for item in agenda.list("active") + agenda.list("all_recent")]
                result["agenda"] = list({item.get("id", index): item for index, item in enumerate(items)}.values())
            except Exception as exc:
                logger.warning("recent context board read failed module=agenda type=%s", type(exc).__name__)
                result["errors"]["agenda"] = "暂时无法读取。"
        cognition = getattr(core, "current_cognition", None)
        if cognition is not None:
            try:
                result["current_cognition"] = cognition.render_for_desk()
            except Exception as exc:
                logger.warning("recent context board read failed module=current_cognition type=%s", type(exc).__name__)
                result["errors"]["current_cognition"] = "暂时无法读取。"
        return result

    @app.post("/api/debug/recent-context")
    async def control_recent_context(body: RecentContextControlRequest):
        builder = getattr(core, "context_builder", None)
        if builder is None:
            raise HTTPException(status_code=409, detail="Context Builder 尚未就绪。")
        if body.agenda_enabled is not None:
            builder.agenda_context_enabled = body.agenda_enabled
        return recent_context_snapshot()

    @app.post("/api/debug/tools/control")
    async def control_tools(body: ToolControlRequest):
        tool_snapshot()
        try:
            core.registry.update_tools(
                name=body.target if body.scope == "tool" else None,
                group=body.target if body.scope == "group" else None,
                enabled=body.enabled,
                force_expose=body.force_expose,
                confirm_write=body.confirm_write,
                reset=body.reset,
            )
        except ZhaoxiError as exc:
            raise HTTPException(status_code=404, detail="钥匙或分组不存在。") from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=409, detail="Tool 设置保存失败，运行状态未修改。") from exc
        return tool_snapshot()

    @app.post("/api/debug/tools/capability")
    async def control_tool_capability(body: ToolCapabilityRequest):
        tool_snapshot()
        try:
            core.registry.update_capability(body.tool, body.capability, body.enabled)
        except (ZhaoxiError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="Tool 能力组不存在。") from exc
        except OSError as exc:
            raise HTTPException(status_code=409, detail="Tool 设置保存失败，运行状态未修改。") from exc
        return tool_snapshot()


    @app.get("/api/reflections")
    async def reflections(limit: int = 20):
        service = getattr(core, "reflection", None)
        if service is None:
            raise HTTPException(status_code=409, detail="Reflection 未启用或当前处于 Setup Mode。")
        try:
            records = await service.repository.list(limit)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"reflections": [_safe_reflection(record) for record in records]}

    @app.post("/api/reflections/{kind}")
    async def generate_reflection(kind: ReflectionKind, regenerate: bool = False):
        service = getattr(core, "reflection", None)
        periods = getattr(core, "reflection_periods", None)
        if service is None or periods is None:
            raise HTTPException(status_code=409, detail="Reflection 未启用或当前处于 Setup Mode。")
        if kind in {ReflectionKind.PROJECT, ReflectionKind.DREAM}:
            raise HTTPException(status_code=422, detail="project/dream 回顾需要明确范围，当前接口暂不支持。")
        try:
            period = periods.resolve(kind)
            with provider_budget_scope(
                configured.request_max_model_calls,
                configured.request_max_total_tokens,
            ):
                record = await service.generate(kind, period, regenerate=regenerate)
        except Exception as exc:
            logger.warning("reflection generation failed type=%s", type(exc).__name__)
            raise HTTPException(status_code=422, detail="回顾生成失败，请稍后重试或检查数据来源。") from exc
        return _safe_reflection(record)

    @app.post("/api/chat/rendered")
    async def reply_rendered(request: ReplyRenderedRequest):
        # Receipt is a server observation of browser acknowledgement, not network-free latency.
        result = adapter.gateway._responses.get(request.request_id)
        if result is None or result.message_id != request.message_id:
            raise HTTPException(status_code=404, detail="找不到对应回复")
        receipts = adapter.gateway.render_receipts
        receipt = receipts.setdefault(request.request_id, {"message_id": request.message_id})
        receipt.update({
            "render_ack_received_at": datetime.now(UTC).isoformat(),
            "first_render_ms": request.first_render_ms,
            "fully_rendered_ms": request.fully_rendered_ms,
        })
        while len(receipts) > 100:
            receipts.popitem(last=False)
        return {"status": "recorded"}

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest):
        request_id = request.request_id or uuid4().hex
        await events.publish({"type": "activity", "label": "正在思考…"})
        try:
            if not request.message.strip() and not request.images:
                raise HTTPException(status_code=422, detail="消息或图片不能为空")
            if request.display_parts and (
                "\n\n".join(p.text for p in request.display_parts if p.text) != request.message.strip()
                or sum(p.image_count for p in request.display_parts) != len(request.images)
            ):
                raise HTTPException(status_code=422, detail="消息显示分段与内容不匹配")
            result = await adapter.chat(
                request.message.strip() or "请查看这些图片。",
                request_id=request_id, images=request.images, display_parts=request.display_parts,
            )
        except HTTPException:
            raise
        except ZhaoxiError as exc:
            code = getattr(exc, "code", "agent_loop_error")
            logger.warning("trace=%s request=%s stage=web event=chat_failed outcome=failed error_code=%s type=%s",
                           request_id, request_id, code, type(exc).__name__)
            raise HTTPException(status_code=422, detail=f"这次操作没成功：{exc}",
                                headers={"X-Zhaoxi-Trace-Id": request_id, "X-Zhaoxi-Error-Code": code}) from exc
        except Exception as exc:
            logger.exception("trace=%s request=%s stage=web event=chat_failed outcome=failed error_code=web_error",
                             request_id, request_id)
            raise HTTPException(status_code=500, detail="这次操作遇到了内部错误，请稍后重试。") from exc
        await events.publish({"type": "activity", "label": "完成", "detail": result.activity})
        return delivered(result)

    @app.post("/api/chat/regenerate", response_model=ChatResponse)
    async def regenerate(request: RegenerateRequest):
        request_id = request.request_id or uuid4().hex
        await events.publish({"type": "activity", "label": "正在重新生成…"})
        try:
            result = await adapter.regenerate(
                request.message_id, request_id=request_id
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ZhaoxiError as exc:
            code = getattr(exc, "code", "agent_loop_error")
            logger.warning("trace=%s request=%s stage=web event=regenerate_failed outcome=failed error_code=%s type=%s",
                           request_id, request_id, code, type(exc).__name__)
            raise HTTPException(status_code=422, detail=f"重新生成失败：{exc}",
                                headers={"X-Zhaoxi-Trace-Id": request_id, "X-Zhaoxi-Error-Code": code}) from exc
        except Exception as exc:
            logger.exception("trace=%s request=%s stage=web event=regenerate_failed outcome=failed error_code=web_error",
                             request_id, request_id)
            raise HTTPException(status_code=500, detail="重新生成遇到了内部错误，请稍后重试。") from exc
        await events.publish({"type": "activity", "label": "完成", "detail": result.activity})
        return delivered(result)

    @app.post("/api/permission/{confirmation_id}/approve", response_model=ChatResponse)
    async def approve(confirmation_id: str, request_id: str | None = None):
        try:
            return delivered(await adapter.resolve_permission(confirmation_id, approve=True, request_id=request_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/permission/{confirmation_id}/deny", response_model=ChatResponse)
    async def deny(confirmation_id: str, request_id: str | None = None):
        try:
            return delivered(await adapter.resolve_permission(confirmation_id, approve=False, request_id=request_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/session")
    async def session():
        return {"messages": await adapter.gateway.history(), "timezone": configured.proactive_timezone}

    @app.post("/api/core/restart")
    async def restart_core():
        if restart_callback is None:
            raise HTTPException(status_code=409, detail="当前运行方式不支持从页面重启 Core。")
        try:
            scheduled = restart_callback()
        except Exception as exc:
            logger.warning("core restart scheduling failed type=%s", type(exc).__name__)
            raise HTTPException(status_code=500, detail="Core 重启请求未能启动。") from exc
        if not scheduled:
            raise HTTPException(status_code=409, detail="Core 已在重启中。")
        return {"status": "restarting"}

    @app.delete("/api/session")
    async def clear_session():
        adapter.clear()
        return {"status": "cleared"}

    @app.get("/api/proactive")
    async def proactive():
        runtime = getattr(core, "proactive", None)
        if runtime is None:
            return {"deliveries": []}
        deliveries = await runtime.store.list_deliveries()
        return {"deliveries": [item.model_dump(mode="json", exclude={"relevant_payload"}) for item in deliveries]}

    @app.post("/api/proactive/{delivery_id}/activate")
    async def activate_delivery(delivery_id: str):
        try:
            return await adapter.gateway.activate_delivery(delivery_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="主动消息不存在或尚未送达。")

    @app.get("/api/proactive/{delivery_id}/inspect")
    async def inspect_delivery(delivery_id: str):
        runtime = getattr(core, "proactive", None)
        delivery = await runtime.store.get_delivery(delivery_id) if runtime else None
        if delivery is None or delivery.status.value not in {"delivered", "acknowledged"}:
            raise HTTPException(status_code=404, detail="主动消息不存在或尚未送达。")
        return delivery.model_dump(mode="json", exclude={"content"})

    @app.get("/api/voice/status")
    async def voice_status():
        if voice_runtime is None:
            return {"enabled": False, "status": "disabled"}
        return {"enabled": True, "status": voice_runtime.status.value}

    @app.post("/api/voice/record/start")
    async def voice_record_start():
        if voice_runtime is None:
            raise HTTPException(status_code=409, detail="Voice 未启用或配置不可用。")
        try:
            await voice_runtime.start_recording(device_name=configured.voice_device_name or None)
        except Exception as exc:
            logger.warning("voice record start failed type=%s", type(exc).__name__)
            raise HTTPException(status_code=422, detail=f"无法开始录音：{exc}") from exc
        return {"status": voice_runtime.status.value}

    @app.post("/api/voice/record/stop")
    async def voice_record_stop():
        if voice_runtime is None:
            raise HTTPException(status_code=409, detail="Voice 未启用或配置不可用。")
        try:
            transcript = await voice_runtime.stop_recording()
        except Exception as exc:
            logger.warning("voice transcription failed type=%s", type(exc).__name__)
            raise HTTPException(status_code=422, detail=f"语音识别失败：{exc}") from exc
        return {
            "status": voice_runtime.status.value,
            "transcript_id": transcript.transcript_id,
            "text": transcript.text,
            "language": transcript.language,
            "provider": transcript.provider,
        }

    @app.post("/api/voice/transcript/confirm", response_model=ChatResponse)
    async def voice_confirm(request: VoiceConfirmRequest):
        if voice_runtime is None:
            raise HTTPException(status_code=409, detail="Voice 未启用或配置不可用。")
        try:
            result = await voice_runtime.confirm_transcript(
                request.text,
                gateway=adapter.gateway,
                request_id=request.request_id,
            )
        except Exception as exc:
            logger.warning("voice transcript confirm failed type=%s", type(exc).__name__)
            raise HTTPException(status_code=422, detail=f"语音消息发送失败：{exc}") from exc
        web_result = adapter._result(result)
        action, _ = voice_policy(
            text=web_result.content,
            explicit=False,
            permission_pending=web_result.permission is not None,
        )
        if action is SpeechAction.SPEAK_NOW:
            await voice_runtime.speak(web_result.content, max_chars=configured.tts_max_chars)
        return delivered(web_result)

    @app.post("/api/voice/cancel")
    async def voice_cancel():
        if voice_runtime is not None:
            await voice_runtime.cancel()
        return {"status": "idle"}

    @app.post("/api/voice/speak")
    async def voice_speak(request: VoiceSpeakRequest):
        if voice_runtime is None:
            raise HTTPException(status_code=409, detail="Voice 未启用或配置不可用。")
        action, reason = voice_policy(text=request.text, explicit=True)
        if action is not SpeechAction.SPEAK_NOW:
            return {"status": voice_runtime.status.value, "started": False, "reason": reason}
        try:
            started = await voice_runtime.speak(request.text, max_chars=configured.tts_max_chars)
        except Exception as exc:
            logger.warning("voice speak failed type=%s", type(exc).__name__)
            raise HTTPException(status_code=422, detail=f"无法朗读：{exc}") from exc
        return {"status": voice_runtime.status.value, "started": started, "reason": "explicit_user_action"}

    @app.post("/api/voice/speak/stop")
    async def voice_speak_stop():
        if voice_runtime is not None:
            await voice_runtime.stop_speaking()
        return {"status": "idle"}

    @app.get("/api/events")
    async def event_stream():
        async def stream():
            yield "event: ready\ndata: {}\n\n"
            async for event in events.subscribe():
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        return StreamingResponse(stream(), media_type="text/event-stream")

    app.state.agent = core
    app.state.adapter = adapter
    app.state.events = events
    return app


def run_web(settings: Settings | None = None) -> None:
    import uvicorn

    configured = settings or Settings()
    print(f"Zhaoxi Local Shell\nhttp://{configured.web_host}:{configured.web_port}")
    uvicorn.run(
        create_app(settings=configured),
        host=configured.web_host,
        port=configured.web_port,
        log_level=configured.log_level.lower(),
    )
