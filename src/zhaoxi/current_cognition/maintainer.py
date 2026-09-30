"""Maintain the journal after final delivery, with a local model-call gate."""
from __future__ import annotations
import asyncio
import json
import logging
import re
from datetime import datetime
from time import monotonic
from zoneinfo import ZoneInfo
from pydantic import ValidationError
from zhaoxi.core.message import Message, Role, is_cognition_message
from zhaoxi.errors import ProviderError
from zhaoxi.models.base import ModelProvider
from zhaoxi.observability import current_trace, llm_owner_scope
from .prompts import MAINTAINER_PROMPT
from .service import CurrentCognitionPatch, CurrentCognitionService

logger = logging.getLogger("CURRENT_COGNITION")
_SIGNAL = re.compile(r"最近|这几天|一直|持续|开始|不再|已经|终于|结束|取消|转向|打算|计划|准备|接下来|秋招|面试|项目|朝汐|寝室|工作|学习|生活|搬|生病|毕业|变化", re.I)
_SMALL = re.compile(r"^(?:哈+|哈哈.+|在吗|小金毛[？?]?|你好|早安|晚安|嗯+|好+|谢谢|今天有点烦|有点烦)[。！!？?~～]*$")

def _parse_patch(raw: str) -> CurrentCognitionPatch:
    content = raw.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    start = content.find("{")
    if start < 0:
        raise ValueError("maintainer response has no JSON object")
    value, _ = json.JSONDecoder().raw_decode(content[start:])
    return CurrentCognitionPatch.model_validate(value)

class CurrentCognitionMaintainer:
    def __init__(self, service: CurrentCognitionService, provider: ModelProvider,
                 *, timezone: str = "Asia/Shanghai") -> None:
        self._lock = asyncio.Lock()
        self.service = service
        self.provider = provider
        self.timezone = ZoneInfo(timezone)

    async def maintain_events(self, stream, *, background: bool = False) -> str:
        from zhaoxi.cognitive_stream.models import CognitiveEventType
        marker = self.service.state().last_processed_message_id
        events = stream.events_after(marker, limit=200)
        trusted = [event for event in events if event.actor_role == "OWNER" and
                   event.event_type in {CognitiveEventType.USER_MESSAGE,
                                        CognitiveEventType.EXTERNAL_MESSAGE} and
                   event.content and event.trust_level in {"TRUSTED", "NORMAL"}]
        messages = [Message(message_id=event.event_id, role=Role.USER,
                            content=event.content, timestamp=event.occurred_at,
                            source=event.source) for event in trusted[:40]]
        return await self.maintain(messages, pending_override=messages, background=background)

    async def maintain(self, messages: list[Message], *, pending_override: list[Message] | None = None,
                       background: bool = False, final_reply: str = "") -> str:
        async with self._lock:
            return await self._maintain(messages, pending_override=pending_override,
                                        background=background, final_reply=final_reply)

    async def _maintain(self, messages: list[Message], *, pending_override: list[Message] | None,
                        background: bool, final_reply: str) -> str:
        state = self.service.state()
        ids = [message.message_id for message in messages]
        if pending_override is not None:
            pending = pending_override
        elif state.last_processed_message_id in ids:
            pending = messages[ids.index(state.last_processed_message_id) + 1:]
        else:
            pending = messages
        last_id = pending[-1].message_id if pending else state.last_processed_message_id or ""
        source_by_id = {m.message_id: m.role.value for m in pending if is_cognition_message(m)}
        evidence_by_id = {m.message_id: (m.content or "")[:1000] for m in pending if is_cognition_message(m)}
        timestamp_by_id = {m.message_id: m.timestamp for m in pending if m.timestamp}
        owner = [m for m in pending if m.role == Role.USER and (m.content or "").strip()]
        signals = [m for m in owner if _SIGNAL.search(m.content or "") and
                   not _SMALL.fullmatch((m.content or "").strip())]
        selected_ids = {m.message_id for m in [*signals[-4:], *owner[-4:]]}
        recent = [m for m in owner if m.message_id in selected_ids][-8:]
        has_signal = bool(signals)
        overdue = any((datetime.now(self.timezone) - t.last_evidence_at).total_seconds() >= 3 * 86400 for t in state.threads)
        overdue |= any((datetime.now(self.timezone) - x.updated_at).total_seconds() >= 3 * 86400 for x in state.recent_changes)
        trace = current_trace()
        if trace:
            trace.emit("current_cognition_gate", "current_cognition", "success", "近期认知本地筛选",
                       metadata={"triggered": has_signal, "reason": "signal" if has_signal else "no_state_change"})
        if not owner or not has_signal:
            reason = "lifecycle_only" if overdue else ("no_owner_message" if not owner else "no_state_change")
            self.service.apply(CurrentCognitionPatch(reason_code=reason, reason=reason),
                               source_by_id=source_by_id, last_message_id=last_id,
                               now=datetime.now(self.timezone), allow_empty_cursor=bool(owner and (state.overview or state.threads or state.recent_changes or state.watch_items)),
                               model_call=False)
            if trace:
                trace.emit("current_cognition_skipped", "current_cognition", "success", "本地跳过模型维护",
                           metadata={"reason": reason})
            return self.service.last_maintenance["decision"]
        if trace:
            trace.emit("current_cognition_triggered", "current_cognition", "success", "需要模型维护",
                       metadata={"reason": "state_signal"})
        evidence = [{"id": m.message_id, "source": m.role.value, "timestamp": m.timestamp.isoformat() if m.timestamp else None,
                     "text": (m.content or "")[:1000]} for m in recent]
        payload = {"current_state": state.model_dump(mode="json", include={"overview", "threads", "recent_changes", "watch_items", "updated_at"}),
                   "new_messages": evidence, "final_reply": final_reply[:350],
                   "now": datetime.now(self.timezone).isoformat(),
                   "task": "BOOTSTRAP" if not state.overview and not state.threads else "MAINTAIN"}
        if payload["task"] == "BOOTSTRAP" and state.last_processed_message_id is None:
            payload["legacy_reference_untrusted"] = self.service.store.legacy_reference()
        diagnostic: dict = {}
        started = monotonic()
        try:
            json_mode = True
            for attempt in (1, 2):
                options = {"max_tokens": 1800 if attempt == 1 else 2600, "temperature": 0}
                if json_mode:
                    options["response_format"] = {"type": "json_object"}
                try:
                    with llm_owner_scope("current_cognition", "current_cognition"):
                        response = await self.provider.generate([
                            Message(role=Role.SYSTEM, content=MAINTAINER_PROMPT),
                            Message(role=Role.USER, content=json.dumps(payload, ensure_ascii=False, default=str)),
                        ], None, **options)
                except ProviderError as exc:
                    if attempt == 1 and exc.code == "provider_http_400" and json_mode:
                        json_mode = False
                        continue
                    raise
                raw = response.content or ""
                diagnostic = {"attempt": attempt, "response_chars": len(raw),
                              "finish_reason": response.finish_reason}
                try:
                    patch = _parse_patch(raw)
                    break
                except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                    diagnostic.update({"error_type": type(exc).__name__, "input_excerpt": raw[:240]})
                    if isinstance(exc, ValidationError):
                        first = exc.errors()[0]
                        diagnostic.update({"field_path": ".".join(map(str, first["loc"])),
                                           "error_message": first["msg"]})
                    else:
                        diagnostic.update({"field_path": "", "error_message": str(exc)[:240]})
                    if attempt == 2:
                        raise
            self.service.apply(patch, source_by_id=source_by_id, evidence_by_id=evidence_by_id,
                               timestamp_by_id=timestamp_by_id, last_message_id=last_id,
                               model_call=True, duration_ms=(monotonic() - started) * 1000,
                               allow_empty_cursor=True)
            if trace:
                trace.emit("current_cognition_applied", "current_cognition", "success", "近期认知操作已处理",
                           metadata={key: self.service.last_maintenance.get(key) for key in
                                     ("ops_count", "threads_added", "threads_updated", "threads_removed",
                                      "duration_ms", "rejection")})
            return "REJECTED" if self.service.last_maintenance.get("rejection") else self.service.last_maintenance["decision"]
        except Exception as exc:
            diagnostic["duration_ms"] = round((monotonic() - started) * 1000, 2)
            logger.warning("COGNITION_MAINTAIN_FAILED type=%s", type(exc).__name__)
            try:
                self.service.record_failure(exc, details=diagnostic)
            except Exception as store_exc:
                logger.warning("COGNITION_DIAGNOSTIC_SAVE_FAILED type=%s", type(store_exc).__name__)
            return "FAILED"
