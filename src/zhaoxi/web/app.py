"""FastAPI application for the local Zhaoxi interaction shell."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from zhaoxi.cli import build_agent
from zhaoxi.config.settings import Settings
from zhaoxi.errors import ZhaoxiError
from zhaoxi.web.adapter import WebInterfaceAdapter, WebResult
from zhaoxi.web.events import EventBroadcaster

logger = logging.getLogger("WEB")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)


class ChatResponse(BaseModel):
    content: str
    activity: dict[str, Any] = Field(default_factory=dict)
    permission: dict[str, Any] | None = None


def _response(result: WebResult) -> ChatResponse:
    return ChatResponse(content=result.content, activity=result.activity, permission=result.permission)


def create_app(*, agent=None, settings: Settings | None = None) -> FastAPI:
    configured = settings or Settings()
    core = agent or build_agent(configured)
    adapter = WebInterfaceAdapter(core)
    events = EventBroadcaster()
    static_dir = Path(__file__).with_name("static")

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
        task = asyncio.create_task(proactive_loop(), name="zhaoxi-proactive-web")
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="Zhaoxi Local Shell", docs_url="/api/docs", lifespan=lifespan)

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(static_dir / "index.html")

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "version": "0.6.1"}

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest):
        await events.publish({"type": "activity", "label": "正在思考…"})
        try:
            result = await adapter.chat(request.message.strip())
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
        return {"messages": adapter.session()}

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
        return {"deliveries": [item.model_dump(mode="json") for item in deliveries]}

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

