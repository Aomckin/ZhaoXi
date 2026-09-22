"""FastAPI application for the local Zhaoxi interaction shell."""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import re
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, ConfigDict, StrictBool, model_validator
from zhaoxi.tools.manifest import group_inventory, inventory_summary
from zhaoxi.tools.filesystem_access import (
    load_filesystem_access,
    resolve_access_directories,
    save_filesystem_access,
    validate_write_subset,
)
from zhaoxi.tools.router import safe_resolve_tool_context

from zhaoxi.cli import build_agent
from zhaoxi import __version__
from zhaoxi.core.suggestions import QuickSuggestions
from zhaoxi.config.settings import Settings
from zhaoxi.errors import ZhaoxiError
from zhaoxi.interfaces.setup import StartupUnavailableAgent
from zhaoxi.reflection.models import ReflectionKind, ReflectionRecord
from zhaoxi.reliability import CorrelationContext, correlation_scope, provider_budget_scope
from zhaoxi.reliability.startup import effective_settings_snapshot, startup_diagnostics
from zhaoxi.web.adapter import WebInterfaceAdapter, WebResult
from zhaoxi.web.events import EventBroadcaster
from zhaoxi.voice.policy import SpeechAction, SpeechContext, SpeechPolicy
from zhaoxi.reliability import TaskSupervisor
from zhaoxi.core.message import Message, Role
from zhaoxi.expression import EmojiMetadata
from zhaoxi.expression.emoji_manager import decode_image_data_url

logger = logging.getLogger("WEB")


from zhaoxi.core.attachments import ImageList


from zhaoxi.interfaces.models import DisplayPart


class ChatRequest(BaseModel):
    message: str = Field(default="", max_length=20_000)
    display_parts: list[DisplayPart] = Field(default_factory=list, max_length=1000)
    images: ImageList = Field(default_factory=list)
    request_id: str | None = Field(default=None, min_length=1, max_length=128)


class ThinkingRequest(BaseModel):
    mode: Literal["off", "disabled", "enabled"]


class RegenerateRequest(BaseModel):
    message_id: str = Field(min_length=1, max_length=128)
    request_id: str | None = Field(default=None, min_length=1, max_length=128)


class ToolControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["tool", "group", "all"]
    target: str | None = None
    enabled: StrictBool | None = None
    force_expose: StrictBool | None = None
    confirm_write: StrictBool | None = None
    reset: bool = False

    @model_validator(mode="after")
    def validate_target(self):
        if self.scope != "all" and not self.target:
            raise ValueError("必须指定钥匙或组")
        if self.scope == "all" and self.target:
            raise ValueError("全部操作不接受 target")
        if self.reset and (self.enabled is not None or self.force_expose is not None or self.confirm_write is not None):
            raise ValueError("恢复默认不能同时指定开关")
        if not self.reset and self.enabled is None and self.force_expose is None and self.confirm_write is None:
            raise ValueError("没有指定修改")
        return self


class InterfaceSettingsRequest(BaseModel):
    input_merge_seconds: int = Field(default=15, ge=0, le=30)
    reply_interval_seconds: int = Field(default=5, ge=0, le=15)
    long_wait_enabled: StrictBool = False


class FilesystemAccessRequest(BaseModel):
    read_directories: list[str] = Field(min_length=1, max_length=20)
    write_directories: list[str] = Field(min_length=1, max_length=20)


class EmojiControlRequest(BaseModel):
    enabled: StrictBool | None = None
    reload: bool = False
    intent: str | None = Field(default=None, max_length=500)
    emotion: str | None = Field(default=None, max_length=80)
    intensity: float | None = Field(default=None, ge=0, le=1)


class EmojiTraceAckRequest(BaseModel):
    trace_id: str = Field(min_length=1, max_length=128)
    received: bool = True
    rendered: bool = True


class EmojiMetadataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=2, max_length=2000)
    tags: list[str] = Field(min_length=1, max_length=50)
    emotion: str | None = Field(default=None, max_length=80)
    intensity: float | None = Field(default=None, ge=0, le=1)
    enabled: bool = True

    def metadata(self) -> EmojiMetadata:
        return EmojiMetadata.model_validate(self.model_dump())


class EmojiCreateRequest(EmojiMetadataRequest):
    data_url: str = Field(min_length=32)


class EmojiPendingRequest(BaseModel):
    data_url: str = Field(min_length=32)


class EmojiAnalyzeRequest(BaseModel):
    data_url: str = Field(min_length=32)
    hint: str = Field(default="", max_length=1000)


def _load_interface_settings(path: Path) -> InterfaceSettingsRequest:
    try:
        return InterfaceSettingsRequest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return InterfaceSettingsRequest()


def _save_interface_settings(path: Path, value: InterfaceSettingsRequest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(path)


def _apply_request_timeout(core, *, enabled: bool, default_seconds: float) -> None:
    timeout = 120 if enabled else default_seconds
    if hasattr(core, "timeout_seconds"):
        core.timeout_seconds = timeout
    provider = getattr(core, "provider", None)
    providers = getattr(provider, "providers", [provider] if provider is not None else [])
    for item in providers:
        if hasattr(item, "timeout"):
            item.timeout = timeout


class ChatResponse(BaseModel):
    timestamp: datetime | None = None
    content: str
    activity: dict[str, Any] = Field(default_factory=dict)
    permission: dict[str, Any] | None = None
    request_id: str | None = None
    trace_id: str | None = None
    status: str = "completed"
    message_id: str | None = None
    output_messages: list[dict[str, Any]] = Field(default_factory=list)


class VoiceConfirmRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    request_id: str | None = Field(default=None, min_length=1, max_length=128)


class VoiceSpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


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
    core_started_at = datetime.now(UTC)
    suggestions = getattr(core, "quick_suggestions", None) or QuickSuggestions(configured.proactive_timezone, configured.quick_suggestions_refresh_minutes)
    events = EventBroadcaster()
    static_dir = Path(__file__).with_name("static")
    speech_policy = SpeechPolicy()
    supervisor = TaskSupervisor()
    current_time = now_provider or (lambda: datetime.now().astimezone())
    interface_settings_path = Path(configured.interface_settings_path)
    filesystem_access_path = Path(configured.filesystem_access_path)
    _apply_request_timeout(
        core,
        enabled=_load_interface_settings(interface_settings_path).long_wait_enabled,
        default_seconds=configured.request_timeout_seconds,
    )

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

    async def proactive_loop() -> None:
        while True:
            await asyncio.sleep(1)
            scheduler = getattr(core, "proactive_scheduler", None)
            runtime = getattr(core, "proactive", None)
            state = getattr(core, "proactive_state", None)
            if scheduler is None or runtime is None or state is None:
                continue
            try:
                emitted = await scheduler.tick()
                for event in emitted:
                    deliveries = await runtime.process(event, datetime.now(UTC), state)
                    for delivery in deliveries:
                        await events.publish({
                            "type": "proactive",
                            "delivery": delivery.model_dump(mode="json"),
                        })
            except Exception as exc:
                logger.warning("proactive web loop failed type=%s", type(exc).__name__)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        supervisor.start()
        heartbeat = getattr(core, "proactive_heartbeat", None)
        worker = getattr(core, "proactive_worker", None)
        if heartbeat is not None and worker is not None:
            if getattr(heartbeat.presence, "run", None):
                supervisor.create(heartbeat.presence.run(), name="zhaoxi-desktop-activity")
            supervisor.create(heartbeat.run(), name="zhaoxi-tidal-heartbeat")
            supervisor.create(worker.run(events.publish), name="zhaoxi-tidal-decisions")
        else:
            supervisor.create(proactive_loop(), name="zhaoxi-proactive-web")
        try:
            yield
        finally:
            if voice_runtime is not None:
                await voice_runtime.cancel("application_shutdown")
            result = await supervisor.shutdown(
                configured.shutdown_grace_seconds, cancel_immediately=True
            )
            registry = getattr(core, "registry", None)
            provider_errors = registry.close_providers() if registry is not None else []
            if provider_errors:
                logger.warning("ToolProvider shutdown failures=%s", provider_errors)
            logger.info(
                "runtime shutdown completed=%s cancelled=%s",
                result["completed"],
                result["cancelled"],
            )

    app = FastAPI(title="Zhaoxi Local Shell", docs_url="/api/docs", lifespan=lifespan)

    if api_token:
        @app.middleware("http")
        async def require_local_token(request: Request, call_next):
            if request.url.path.startswith("/api/") and request.url.path != "/api/bootstrap":
                supplied = request.headers.get("X-Zhaoxi-Token") or request.cookies.get(
                    "zhaoxi_session", ""
                )
                if not secrets.compare_digest(supplied, api_token):
                    return JSONResponse(status_code=401, content={"detail": "本地 Desktop 会话令牌无效。"})
            return await call_next(request)

    from fastapi.staticfiles import StaticFiles

    mimetypes.add_type("image/webp", ".webp")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.middleware("http")
    async def desktop_entry_guard(request: Request, call_next):
        import posixpath
        normalized_path = posixpath.normpath(request.url.path.replace("\\", "/")).lower().rstrip(" .")
        if (normalized_path == "/" or normalized_path.startswith("/static/") and normalized_path.endswith(".html")) and not configured.dev_browser_ui:
            supplied = request.cookies.get("zhaoxi_session", "")
            if not api_token or not secrets.compare_digest(supplied, api_token):
                return JSONResponse(status_code=403, content={"detail": "请从桌面或托盘打开朝汐。开发调试可设置 ZHAOXI_DEV_BROWSER_UI=true。"})
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

    @app.get("/api/suggestions")
    async def quick_suggestions():
        state = getattr(core, "proactive_state", None)
        heartbeat = getattr(core, "proactive_heartbeat", None)
        snapshot = suggestions.get(core.conversation, state,
            focus=bool(heartbeat and heartbeat.focus_active),
            recent_proactive=any(m.delivery_id for m in core.conversation.messages))
        return {**snapshot, "timezone": configured.proactive_timezone}

    def thinking_provider():
        provider = getattr(core, "provider", None)
        return provider.providers[0] if getattr(provider, "providers", None) else provider

    def thinking_mode() -> str:
        enabled = getattr(thinking_provider(), "thinking_enabled", None)
        if enabled is None:
            return "off"
        return "enabled" if enabled else "disabled"

    @app.get("/api/settings/thinking")
    async def thinking_settings():
        return {"mode": thinking_mode()}

    @app.put("/api/settings/thinking")
    async def change_thinking(request: ThinkingRequest):
        provider = thinking_provider()
        if not hasattr(provider, "set_thinking"):
            raise HTTPException(status_code=409, detail="模型接口尚未就绪")
        enabled = {"off": None, "disabled": False, "enabled": True}[request.mode]
        provider.set_thinking(enabled)
        return {"mode": thinking_mode()}

    @app.get("/api/settings/interface")
    async def interface_settings():
        return _load_interface_settings(interface_settings_path)

    @app.put("/api/settings/interface")
    async def change_interface_settings(request: InterfaceSettingsRequest):
        try:
            _save_interface_settings(interface_settings_path, request)
        except OSError as exc:
            logger.warning("interface settings persistence failed type=%s", type(exc).__name__)
            raise HTTPException(status_code=500, detail="界面设置保存失败。") from exc
        _apply_request_timeout(
            core,
            enabled=request.long_wait_enabled,
            default_seconds=configured.request_timeout_seconds,
        )
        return request

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
            "sensor_health": getattr(getattr(core, "proactive_heartbeat", None), "sensor_health", {}),
            "active": (core.proactive_state.interaction.beat_loop.diagnostics(datetime.now(UTC))
                if getattr(core, "proactive_state", None) and core.proactive_state.interaction.beat_loop else None),
            "desktop_activity": (core.proactive_state.interaction.desktop_activity.diagnostics()
                if getattr(core, "proactive_state", None) and core.proactive_state.interaction.desktop_activity
                else {"enabled": False}),
            "quick_suggestions_generated": suggestions.generated,
            "quick_suggestions_llm_calls": 0,
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

    @app.get("/api/debug/tools")
    async def debug_tools():
        return tool_snapshot()

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

    def emoji_service():
        service = getattr(core, "emoji_service", None)
        if service is None:
            raise HTTPException(status_code=409, detail="Emoji Module 尚未就绪。")
        return service

    def emoji_manager():
        manager = getattr(core, "emoji_manager", None)
        if manager is None:
            raise HTTPException(status_code=409, detail="表情柜尚未就绪。")
        return manager

    @app.get("/api/debug/emoji")
    async def debug_emoji():
        manager = getattr(core, "emoji_manager", None)
        return {**emoji_service().diagnostics(), **(manager.diagnostics() if manager else {})}

    @app.post("/api/debug/emoji")
    async def control_emoji(body: EmojiControlRequest):
        service = emoji_service()
        if body.enabled is not None:
            service.enabled = body.enabled
        if body.reload:
            service.reload()
        if body.intent and body.intent.strip():
            service.search(body.intent, body.emotion, body.intensity)
        manager = getattr(core, "emoji_manager", None)
        return {**service.diagnostics(), **(manager.diagnostics() if manager else {})}

    @app.get("/api/debug/emoji/trace")
    async def emoji_trace():
        return getattr(core, "last_emoji_trace", {})

    @app.post("/api/debug/emoji/trace/ack")
    async def acknowledge_emoji_trace(body: EmojiTraceAckRequest):
        trace = getattr(core, "last_emoji_trace", {})
        if trace.get("trace_id") != body.trace_id:
            raise HTTPException(status_code=409, detail="该表情 Trace 已不是最近一次请求。")
        trace["frontend_received"] = body.received
        trace["frontend_rendered"] = body.rendered
        logger.info(
            "emoji frontend_received=%s frontend_rendered=%s",
            body.received,
            body.rendered,
        )
        return trace

    @app.post("/api/debug/emoji/direct")
    async def debug_emoji_direct():
        """Exercise Reply DSL -> Resolver -> Message -> Store -> Gateway."""
        trace_id = f"emoji_direct_{uuid4().hex}"
        async with adapter.gateway._lock:
            with correlation_scope(CorrelationContext(trace_id=trace_id, request_id=trace_id, session_id="local")):
                service = emoji_service()
                sample = service.entries[0]
                previous = {id(item) for item in core.conversation.messages}
                core._commit_model_reply(f"[emoji:{','.join(sample.tags[:3])}]")
                await adapter.gateway._persist_session()
                messages = [
                    adapter.gateway._message_view(item)
                    for item in core.conversation.messages
                    if id(item) not in previous and item.role.value == "assistant"
                ]
                core.last_emoji_trace["persisted"] = True
                core.last_emoji_trace["gateway_emitted"] = bool(messages)
                return {"trace_id": trace_id, "trace": core.last_emoji_trace, "messages": messages}

    @app.post("/api/debug/emoji/model")
    async def debug_emoji_model():
        result = await adapter.chat(
            "请在完整回复中使用 Reply DSL 表达此刻测试成功的心情。",
            request_id=f"emoji_model_{uuid4().hex}",
        )
        return _response(result)

    @app.get("/api/emoji")
    async def list_emoji(q: str = "", enabled: bool | None = None):
        values = emoji_manager().list_all(q, enabled)
        return {"items": values, "count": len(values), **emoji_manager().diagnostics()}

    @app.post("/api/emoji")
    async def create_emoji(body: EmojiCreateRequest):
        try:
            return emoji_manager().add_data_url(body.data_url, body.metadata())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/emoji/reload")
    async def reload_emoji():
        return {"status": "reloaded", "loaded_emojis": emoji_service().reload()}

    @app.get("/api/emoji/pending")
    async def list_pending_emoji():
        values = emoji_manager().list_pending()
        return {"items": values, "count": len(values)}

    @app.post("/api/emoji/pending")
    async def add_pending_emoji(body: EmojiPendingRequest):
        try:
            return emoji_manager().add_pending(body.data_url)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/emoji/pending/{pending_id}/image", include_in_schema=False)
    async def pending_emoji_image(pending_id: str):
        path = emoji_manager().pending_path(pending_id)
        if path is None:
            raise HTTPException(status_code=404, detail="待整理图片不存在。")
        return FileResponse(path, headers={"Cache-Control": "no-store"})

    @app.delete("/api/emoji/pending/{pending_id}")
    async def delete_pending_emoji(pending_id: str):
        result = emoji_manager().delete_pending(pending_id)
        if result.status == "not_found":
            raise HTTPException(status_code=404, detail="待整理图片不存在。")
        return result

    @app.post("/api/emoji/pending/{pending_id}/commit")
    async def commit_pending_emoji(pending_id: str, body: EmojiMetadataRequest):
        result = emoji_manager().commit_pending(pending_id, body.metadata())
        if result.status == "not_found":
            raise HTTPException(status_code=404, detail="待整理图片不存在。")
        return result

    @app.post("/api/emoji/analyze")
    async def analyze_emoji(body: EmojiAnalyzeRequest):
        try:
            decode_image_data_url(body.data_url)
            provider = getattr(core, "provider", None)
            if provider is None:
                raise ValueError("当前模型不可用")
            prompt = (
                "分析这张表情图片，并结合用户提示生成其表达含义和适用语境。只返回 JSON："
                '{"description":"...","tags":["..."],"emotion":"...","intensity":0.5}。'
                "description 不要只描述画面；tags 使用自然中文短词；不要过度脑补。\n用户提示："
                + (body.hint or "无")
            )
            with provider_budget_scope(configured.request_max_model_calls, configured.request_max_total_tokens):
                response = await provider.generate([
                    Message(role=Role.SYSTEM, content="你负责为本地表情收藏生成简洁、可靠的语义元数据。"),
                    Message(role=Role.USER, content=prompt, images=[body.data_url]),
                ])
            text = (response.content or "").strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
            value = json.loads(text)
            return EmojiMetadata.model_validate(value).model_dump(mode="json")
        except Exception as exc:
            logger.warning("emoji analysis failed type=%s", type(exc).__name__)
            raise HTTPException(status_code=422, detail="表情识别失败，请手工填写或稍后重试。") from exc

    @app.get("/api/emoji/{emoji_id}")
    async def get_emoji(emoji_id: str):
        item = emoji_manager().get(emoji_id)
        if item is None:
            raise HTTPException(status_code=404, detail="表情不存在。")
        return {**item.model_dump(mode="json"), "url": f"/api/expression/emoji/{emoji_id}"}

    @app.patch("/api/emoji/{emoji_id}")
    async def update_emoji(emoji_id: str, body: EmojiMetadataRequest):
        result = emoji_manager().update_metadata(emoji_id, body.metadata())
        if result.status == "not_found":
            raise HTTPException(status_code=404, detail="表情不存在。")
        return result

    @app.delete("/api/emoji/{emoji_id}")
    async def delete_emoji(emoji_id: str):
        result = emoji_manager().delete(emoji_id)
        if result.status == "not_found":
            raise HTTPException(status_code=404, detail="表情不存在。")
        return result

    @app.get("/api/expression/emoji/{emoji_id}", include_in_schema=False)
    async def emoji_image(emoji_id: str):
        manager = getattr(core, "emoji_manager", None)
        path = manager.image_path(emoji_id) if manager is not None else emoji_service().image_path(emoji_id)
        if path is None:
            raise HTTPException(status_code=404, detail="表情不存在或已停用。")
        return FileResponse(path, headers={"Cache-Control": "no-store"})

    @app.put("/api/tools/filesystem-access")
    async def change_filesystem_access(body: FilesystemAccessRequest):
        try:
            read_directories = resolve_access_directories(body.read_directories)
            write_directories = resolve_access_directories(body.write_directories)
            validate_write_subset(read_directories, write_directories)
            save_filesystem_access(
                filesystem_access_path,
                read_directories=read_directories,
                write_directories=write_directories,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except OSError as exc:
            logger.warning("filesystem access persistence failed type=%s", type(exc).__name__)
            raise HTTPException(status_code=500, detail="允许目录保存失败。") from exc
        return {
            "read_directories": read_directories,
            "write_directories": write_directories,
            "restart_required": True,
            "message": "已保存，重启 Core 后生效。",
        }

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

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest):
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
                request_id=request.request_id, images=request.images, display_parts=request.display_parts,
            )
        except HTTPException:
            raise
        except ZhaoxiError as exc:
            logger.warning("web chat core error type=%s", type(exc).__name__)
            raise HTTPException(status_code=422, detail=f"这次操作没成功：{exc}") from exc
        except Exception as exc:
            logger.exception("unexpected web chat failure")
            raise HTTPException(status_code=500, detail="这次操作遇到了内部错误，请稍后重试。") from exc
        await events.publish({"type": "activity", "label": "完成", "detail": result.activity})
        return _response(result)

    @app.post("/api/chat/regenerate", response_model=ChatResponse)
    async def regenerate(request: RegenerateRequest):
        await events.publish({"type": "activity", "label": "正在重新生成…"})
        try:
            result = await adapter.regenerate(
                request.message_id, request_id=request.request_id
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ZhaoxiError as exc:
            logger.warning("web regenerate core error type=%s", type(exc).__name__)
            raise HTTPException(status_code=422, detail=f"重新生成失败：{exc}") from exc
        except Exception as exc:
            logger.exception("unexpected web regenerate failure")
            raise HTTPException(status_code=500, detail="重新生成遇到了内部错误，请稍后重试。") from exc
        await events.publish({"type": "activity", "label": "完成", "detail": result.activity})
        return _response(result)

    @app.post("/api/permission/{confirmation_id}/approve", response_model=ChatResponse)
    async def approve(confirmation_id: str):
        try:
            return _response(await adapter.resolve_permission(confirmation_id, approve=True))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/permission/{confirmation_id}/deny", response_model=ChatResponse)
    async def deny(confirmation_id: str):
        try:
            return _response(await adapter.resolve_permission(confirmation_id, approve=False))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/session")
    async def session():
        return {"messages": await adapter.gateway.history()}

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
        return _response(web_result)

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
