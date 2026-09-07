"""FastAPI application for the local Zhaoxi interaction shell."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from zhaoxi.cli import build_agent
from zhaoxi import __version__
from zhaoxi.core.suggestions import QuickSuggestions
from zhaoxi.config.settings import Settings
from zhaoxi.errors import ZhaoxiError
from zhaoxi.interfaces.setup import StartupUnavailableAgent
from zhaoxi.reflection.models import ReflectionKind, ReflectionRecord
from zhaoxi.reliability import provider_budget_scope
from zhaoxi.reliability.startup import startup_diagnostics
from zhaoxi.web.adapter import WebInterfaceAdapter, WebResult
from zhaoxi.web.events import EventBroadcaster
from zhaoxi.voice.policy import SpeechAction, SpeechContext, SpeechPolicy
from zhaoxi.reliability import TaskSupervisor

logger = logging.getLogger("WEB")


from zhaoxi.core.attachments import ImageList


class ChatRequest(BaseModel):
    message: str = Field(default="", max_length=20_000)
    images: ImageList = Field(default_factory=list)
    request_id: str | None = Field(default=None, min_length=1, max_length=128)


class ChatResponse(BaseModel):
    timestamp: datetime | None = None
    content: str
    activity: dict[str, Any] = Field(default_factory=dict)
    permission: dict[str, Any] | None = None
    request_id: str | None = None
    trace_id: str | None = None
    status: str = "completed"


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
    suggestions = getattr(core, "quick_suggestions", None) or QuickSuggestions(configured.proactive_timezone, configured.quick_suggestions_refresh_minutes)
    events = EventBroadcaster()
    static_dir = Path(__file__).with_name("static")
    speech_policy = SpeechPolicy()
    supervisor = TaskSupervisor()
    current_time = now_provider or (lambda: datetime.now().astimezone())

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

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(static_dir / "index.html")

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

    @app.get("/api/diagnostics")
    async def diagnostics():
        """Return a bounded, content-free local runtime snapshot."""
        backup_manager = getattr(core, "backup_manager", None)
        return {
            "status": "ok",
            "version": __version__,
            "metrics": adapter.gateway.metrics.snapshot(),
            "presence": (core.proactive_state.interaction.diagnostics(datetime.now(UTC))
                         if getattr(core, "proactive_state", None) else None),
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
            "tool_packages": getattr(core, "tool_packages", []),
            "tool_package_errors": getattr(core, "tool_package_errors", []),
            "startup": getattr(core, "startup_diagnostics", None),
            "storage": backup_manager.health() if backup_manager is not None else {},
        }

    @app.get("/api/capabilities")
    async def capabilities():
        """Describe installed capabilities without exposing schemas or user data."""
        catalog = getattr(core, "capability_catalog", None)
        if catalog is not None:
            return catalog
        registry = getattr(core, "registry", None)
        return {
            "status": "ready",
            "tools": [
                {"name": tool.name, "description": tool.description}
                for tool in (registry.list() if registry is not None else [])
            ],
            "workflows": [],
            "packages": [],
            "examples": [],
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
            result = await adapter.chat(
                request.message.strip() or "请查看这些图片。",
                request_id=request.request_id, images=request.images,
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
