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


class ReplyRenderedRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=128)
    message_id: str = Field(min_length=1, max_length=128)
    first_render_ms: float | None = Field(default=None, ge=0, le=300_000)
    fully_rendered_ms: float | None = Field(default=None, ge=0, le=300_000)


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


class ToolCapabilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str = Field(min_length=1)
    capability: str = Field(min_length=1)
    enabled: StrictBool


class InterfaceSettingsRequest(BaseModel):
    input_merge_seconds: int = Field(default=15, ge=0, le=30)
    reply_interval_seconds: int = Field(default=5, ge=0, le=15)
    external_input_debounce_seconds: float = Field(default=5, ge=0, le=15)
    external_reply_interval_seconds: float = Field(default=0.5, ge=0, le=5)
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


class RecentContextControlRequest(BaseModel):
    agenda_enabled: StrictBool | None = None


class InternalActivityDebugRequest(BaseModel):
    activity: Literal["tick", "current_cognition_consolidation", "memory_maintenance",
                      "agenda_maintenance", "proactive_check"] = "tick"


class DecisionDebugRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    forced_level: Literal["L0", "L1", "L2"] | None = None


class PresenceDebugRequest(BaseModel):
    state: Literal["ACTIVE", "SEMI_ACTIVE", "AWAY"] | None = Field(...)


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
    supervisor = TaskSupervisor()
    perception = None
    source_runtime = None
    if configured.perception_enabled and not isinstance(core, StartupUnavailableAgent):
        try:
            from zhaoxi.perception import PerceptionRuntime
            from zhaoxi.plugins.runtime import PluginRuntime
            from zhaoxi.plugins.source_router import PerceptionSink
            from zhaoxi.plugins.loader import discover
            import tomllib
            perception = PerceptionRuntime(configured, core)
            core.perception = perception
            source_runtime = PluginRuntime(None)
            source_runtime.sink = PerceptionSink(perception, source_runtime)
            perception.sources = source_runtime
            plugin_dir = Path(__file__).resolve().parents[2] / "zhaoxi_ext"
            discovery_errors = []
            manifests = discover(plugin_dir, discovery_errors)
            for plugin_id, manifest in discover(Path("plugins/external_sources"), discovery_errors).items():
                if plugin_id in manifests:
                    discovery_errors.append((plugin_id, "DuplicatePluginId"))
                else:
                    manifests[plugin_id] = manifest
            for bad_id, error in discovery_errors:
                from zhaoxi.plugins.manifests import PluginManifest
                safe_id = "invalid_" + re.sub(r"[^a-z0-9_]", "_", bad_id.lower())
                broken = PluginManifest(id=safe_id, name=bad_id, version="invalid",
                                        entrypoint="invalid:Invalid")
                if safe_id in source_runtime._state:
                    continue
                source_runtime.register(broken)
                source_runtime._state[safe_id]["status"] = "degraded"
                source_runtime._state[safe_id]["last_error"] = error
                logger.warning("external source manifest failed id=%s error=%s", bad_id, error)
            for manifest in manifests.values():
                config_path = Path("config/plugins") / (manifest.id + ".toml")
                try:
                    if config_path.is_file():
                        with config_path.open("rb") as stream:
                            enabled = bool(tomllib.load(stream).get("enabled", False))
                    else:
                        enabled = False
                    source_runtime.register(manifest, enabled=enabled)
                except Exception as exc:
                    source_runtime.register(manifest)
                    state = source_runtime._state[manifest.id]
                    state["status"] = "degraded"
                    state["last_error"] = type(exc).__name__
        except Exception as exc:
            logger.warning("perception startup degraded type=%s", type(exc).__name__)
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

    async def internal_activity_loop() -> None:
        while True:
            activity = getattr(core, "internal_activity", None)
            if activity is not None:
                try:
                    await activity.run_tick()
                except Exception as exc:
                    logger.warning("internal activity loop failed type=%s", type(exc).__name__)
            await asyncio.sleep(configured.proactive_heartbeat_seconds)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        supervisor.start()
        adapter.gateway.maintenance_queue().start()
        heartbeat = getattr(core, "proactive_heartbeat", None)
        worker = getattr(core, "proactive_worker", None)
        if heartbeat is not None and worker is not None:
            if getattr(heartbeat.presence, "run", None):
                supervisor.create(heartbeat.presence.run(), name="zhaoxi-desktop-activity")
            supervisor.create(heartbeat.run(), name="zhaoxi-tidal-heartbeat")
            supervisor.create(worker.run(events.publish), name="zhaoxi-tidal-decisions")
        else:
            supervisor.create(proactive_loop(), name="zhaoxi-proactive-web")
            supervisor.create(internal_activity_loop(), name="zhaoxi-internal-activity")
        if perception is not None:
            supervisor.create(perception.run(), name="zhaoxi-perception")
        if source_runtime is not None:
            for source in source_runtime.diagnostics():
                if source["enabled"]:
                    await source_runtime.enable(source["plugin_id"])
        try:
            yield
        finally:
            if source_runtime is not None:
                await source_runtime.stop()
            if perception is not None:
                try:
                    await asyncio.wait_for(perception.flush(force=True), timeout=5)
                except Exception as exc:
                    logger.warning("perception shutdown flush deferred type=%s", type(exc).__name__)
            if voice_runtime is not None:
                await voice_runtime.cancel("application_shutdown")
            await adapter.gateway.maintenance_queue().shutdown(configured.shutdown_grace_seconds)
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

    @app.get("/api/perception/inspect")
    async def perception_inspect():
        return perception.diagnostics() if perception else {"enabled": False}

    @app.post("/api/perception/flush")
    async def perception_flush():
        if perception is None:
            raise HTTPException(status_code=503, detail="Perception 未启用")
        return {"batches": await perception.flush(force=True)}

    @app.post("/api/perception/clear-expired")
    async def perception_clear_expired():
        if perception is None:
            raise HTTPException(status_code=503, detail="Perception 未启用")
        return {"deleted": perception.store.clear_expired(configured.perception_observation_ttl_hours)}

    @app.get("/api/perception/recent")
    async def perception_recent():
        if perception is None:
            raise HTTPException(status_code=503, detail="Perception 未启用")
        return {"observations": [x.model_dump(mode="json") for x in perception.store.recent_observations()],
                "snapshots": [x.model_dump(mode="json") for x in perception.store.recent_all_snapshots()]}

    @app.get("/api/perception/sessions")
    async def perception_sessions():
        if perception is None:
            raise HTTPException(status_code=503, detail="Perception 未启用")
        sessions = await core.session_store.list()
        return {"sessions": [{"id": item.id, "updated_at": item.updated_at.isoformat(),
                              "messages": len(item.conversation.messages)}
                             for item in sessions if item.id.count("/") >= 2 and not item.id.startswith("local/")][:30]}

    @app.get("/api/perception/self-events")
    async def perception_self_events():
        if perception is None:
            raise HTTPException(status_code=503, detail="Perception 未启用")
        return {"events": [item.model_dump(mode="json") for item in perception.ledger.recent(20)]}

    @app.post("/api/perception/process-pending")
    async def perception_process_pending():
        if perception is None:
            raise HTTPException(status_code=503, detail="Perception 未启用")
        return {"processed": await perception.process_pending_snapshot()}

    @app.post("/api/perception/clear-ledger")
    async def perception_clear_ledger():
        if perception is None:
            raise HTTPException(status_code=503, detail="Perception 未启用")
        return {"deleted": perception.ledger.clear_expired()}

    @app.post("/api/perception/resolve-last-image")
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

    @app.get("/api/perception/expression")
    async def perception_expression():
        from zhaoxi.perception.context import ChannelExpressionPolicy
        return {"private": ChannelExpressionPolicy.prompt("private"),
                "group": ChannelExpressionPolicy.prompt("group")}

    @app.get("/api/external-sources")
    async def external_sources():
        return source_runtime.diagnostics() if source_runtime else []

    @app.post("/api/external-sources/{plugin_id}/enable")
    async def enable_external_source(plugin_id: str):
        if source_runtime is None or plugin_id not in source_runtime._state:
            raise HTTPException(status_code=404, detail="Source unavailable")
        await source_runtime.enable(plugin_id)
        return source_runtime.diagnostics()

    @app.post("/api/external-sources/{plugin_id}/disable")
    async def disable_external_source(plugin_id: str):
        if source_runtime is None or plugin_id not in source_runtime._state:
            raise HTTPException(status_code=404, detail="Source unavailable")
        await source_runtime.disable(plugin_id)
        return source_runtime.diagnostics()

    @app.post("/api/external-sources/{plugin_id}/restart")
    async def restart_external_source(plugin_id: str):
        if source_runtime is None or plugin_id not in source_runtime._state:
            raise HTTPException(status_code=404, detail="Source unavailable")
        await source_runtime.restart(plugin_id)
        return source_runtime.diagnostics()

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
                "maintenance": adapter.gateway.maintenance_queue().diagnostics(),
                "render_receipts": dict(adapter.gateway.render_receipts)}

    @app.get("/api/debug/memory-retrieval")
    async def debug_memory_retrieval(query: str, limit: int = 10):
        if not configured.memory_retrieval_debug_enabled:
            raise HTTPException(status_code=404, detail="Memory Inspector 未启用。")
        service = getattr(core, "memory_service", None)
        if service is None:
            raise HTTPException(status_code=409, detail="Memory 尚未就绪。")
        from zhaoxi.memory.models import MemoryQuery
        items = await service.inspect_retrieval(MemoryQuery(text=query[:1000], limit=max(1, min(limit, 30))))
        return {"query": query[:1000], "candidates": [{
            "content": item["record"]["content"], "final_score": item["score"],
            "contextual_relevance": item["contextual_relevance"],
            "text_score": item["text_score"], "semantic_score": item["semantic_score"],
            "graph_score": item["graph_score"], "time_score": item["time_score"],
            "activation_score": item["activation_score"], "importance_score": item["importance_score"],
            "status": item["record"]["status"], "importance": item["record"]["importance"],
            "activation": item["record"]["activation"], "why_selected": item["why_selected"],
        } for item in items]}

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
        service = getattr(core, "decision_service", None)
        if service is None:
            raise HTTPException(status_code=409, detail="Decision Layer 尚未就绪。")
        return service.diagnostics()

    @app.post("/api/debug/decision")
    async def debug_evaluate_decision(body: DecisionDebugRequest):
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
        return state.interaction.diagnostics(now)

    @app.post("/api/debug/internal-activity")
    async def run_debug_internal_activity(body: InternalActivityDebugRequest):
        activity = getattr(core, "internal_activity", None)
        if activity is None:
            raise HTTPException(status_code=409, detail="Internal Activity 尚未就绪。")
        deliveries = await activity.run_tick(force=None if body.activity == "tick" else body.activity)
        for delivery in deliveries:
            await events.publish({"type": "proactive", "delivery": delivery.model_dump(mode="json", exclude={"relevant_payload"})})
        return activity.diagnostics()

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
                state = cognition.state()
                sections = {category: [] for category in ("active_context", "active_thread", "recent_topic", "recent_change", "unresolved")}
                sections["active_thread"] = state.ongoing_threads
                sections["unresolved"] = state.attention
                result["current_cognition"] = {
                    "overview": state.narrative,
                    "sections": sections,
                    "updated_at": state.updated_at.isoformat() if state.updated_at else None,
                }
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
        return delivered(result)

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
