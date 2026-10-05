"""Emoji api routes with explicit application dependencies."""
import json
import logging
import re
from uuid import uuid4
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from zhaoxi.core.message import Message, Role
from zhaoxi.expression import EmojiMetadata
from zhaoxi.expression.emoji_manager import decode_image_data_url
from zhaoxi.reliability import CorrelationContext, correlation_scope, provider_budget_scope
from .schemas import (EmojiControlRequest, EmojiTraceAckRequest, EmojiCreateRequest,
                      EmojiPendingRequest, EmojiAnalyzeRequest, EmojiMetadataRequest)
logger = logging.getLogger("WEB")


def emoji_api_router(core, configured, adapter, delivered):
    router = APIRouter()

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


    @router.get("/api/debug/emoji")
    async def debug_emoji():
        manager = getattr(core, "emoji_manager", None)
        return {**emoji_service().diagnostics(), **(manager.diagnostics() if manager else {})}


    @router.post("/api/debug/emoji")
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


    @router.get("/api/debug/emoji/trace")
    async def emoji_trace():
        return getattr(core, "last_emoji_trace", {})


    @router.post("/api/debug/emoji/trace/ack")
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


    @router.post("/api/debug/emoji/direct")
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


    @router.post("/api/debug/emoji/model")
    async def debug_emoji_model():
        result = await adapter.chat(
            "请在完整回复中使用 Reply DSL 表达此刻测试成功的心情。",
            request_id=f"emoji_model_{uuid4().hex}",
        )
        return delivered(result)


    @router.get("/api/emoji")
    async def list_emoji(q: str = "", enabled: bool | None = None):
        values = emoji_manager().list_all(q, enabled)
        return {"items": values, "count": len(values), **emoji_manager().diagnostics()}


    @router.post("/api/emoji")
    async def create_emoji(body: EmojiCreateRequest):
        try:
            return emoji_manager().add_data_url(body.data_url, body.metadata())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


    @router.post("/api/emoji/reload")
    async def reload_emoji():
        return {"status": "reloaded", "loaded_emojis": emoji_service().reload()}


    @router.get("/api/emoji/pending")
    async def list_pending_emoji():
        values = emoji_manager().list_pending()
        return {"items": values, "count": len(values)}


    @router.post("/api/emoji/pending")
    async def add_pending_emoji(body: EmojiPendingRequest):
        try:
            return emoji_manager().add_pending(body.data_url)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


    @router.get("/api/emoji/pending/{pending_id}/image", include_in_schema=False)
    async def pending_emoji_image(pending_id: str):
        path = emoji_manager().pending_path(pending_id)
        if path is None:
            raise HTTPException(status_code=404, detail="待整理图片不存在。")
        return FileResponse(path, headers={"Cache-Control": "no-store"})


    @router.delete("/api/emoji/pending/{pending_id}")
    async def delete_pending_emoji(pending_id: str):
        result = emoji_manager().delete_pending(pending_id)
        if result.status == "not_found":
            raise HTTPException(status_code=404, detail="待整理图片不存在。")
        return result


    @router.post("/api/emoji/pending/{pending_id}/commit")
    async def commit_pending_emoji(pending_id: str, body: EmojiMetadataRequest):
        result = emoji_manager().commit_pending(pending_id, body.metadata())
        if result.status == "not_found":
            raise HTTPException(status_code=404, detail="待整理图片不存在。")
        return result


    @router.post("/api/emoji/analyze")
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


    @router.get("/api/emoji/{emoji_id}")
    async def get_emoji(emoji_id: str):
        item = emoji_manager().get(emoji_id)
        if item is None:
            raise HTTPException(status_code=404, detail="表情不存在。")
        return {**item.model_dump(mode="json"), "url": f"/api/expression/emoji/{emoji_id}"}


    @router.patch("/api/emoji/{emoji_id}")
    async def update_emoji(emoji_id: str, body: EmojiMetadataRequest):
        result = emoji_manager().update_metadata(emoji_id, body.metadata())
        if result.status == "not_found":
            raise HTTPException(status_code=404, detail="表情不存在。")
        return result


    @router.delete("/api/emoji/{emoji_id}")
    async def delete_emoji(emoji_id: str):
        result = emoji_manager().delete(emoji_id)
        if result.status == "not_found":
            raise HTTPException(status_code=404, detail="表情不存在。")
        return result


    @router.get("/api/expression/emoji/{emoji_id}", include_in_schema=False)
    async def emoji_image(emoji_id: str):
        manager = getattr(core, "emoji_manager", None)
        path = manager.image_path(emoji_id) if manager is not None else emoji_service().image_path(emoji_id)
        if path is None:
            raise HTTPException(status_code=404, detail="表情不存在或已停用。")
        return FileResponse(path, headers={"Cache-Control": "no-store"})


    return router
