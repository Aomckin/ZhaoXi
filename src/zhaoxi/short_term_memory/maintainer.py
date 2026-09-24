"""Inspect each completed turn and apply only evidence-bound changes."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from zhaoxi.core.message import Message, Role
from zhaoxi.errors import ProviderError
from zhaoxi.models.base import ModelProvider

from .prompts import MAINTAINER_PROMPT
from .service import ShortTermMemoryPatch, ShortTermMemoryService

logger = logging.getLogger("STM")


def _parse_patch(raw: str) -> ShortTermMemoryPatch:
    """Accept a JSON object with harmless surrounding text, but never guess missing fields."""
    content = raw.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    start = content.find("{")
    if start < 0:
        raise ValueError("maintainer response has no JSON object")
    value, _ = json.JSONDecoder().raw_decode(content[start:])
    patch = ShortTermMemoryPatch.model_validate(value)
    if patch.action == "NO_CHANGE" and any((patch.add, patch.update, patch.reinforce, patch.fade, patch.remove)):
        raise ValueError("NO_CHANGE cannot contain edits")
    return patch


class ShortTermMemoryMaintainer:
    def __init__(self, service: ShortTermMemoryService, provider: ModelProvider,
                 *, timezone: str = "Asia/Shanghai") -> None:
        self.service = service
        self.provider = provider
        self.timezone = ZoneInfo(timezone)

    async def maintain(self, messages: list[Message], *, pending_override: list[Message] | None = None) -> str:
        state = self.service.state()
        if not messages:
            return "NO_CHANGE"
        ids = [message.message_id for message in messages]
        if pending_override is not None:
            pending = pending_override
        elif state.last_processed_message_id in ids:
            pending = messages[ids.index(state.last_processed_message_id) + 1:]
        else:
            pending = messages
        if not pending:
            return "NO_CHANGE"
        last_id = pending[-1].message_id
        evidence = []
        source_by_id = {}
        evidence_by_id = {}
        for message in pending:
            if message.role not in {Role.USER, Role.TOOL, Role.ASSISTANT} or not message.content:
                continue
            source_by_id[message.message_id] = message.role.value
            text = message.content[:1200]
            if message.role == Role.TOOL:
                # Tool payload is evidence only when it reports a successful result.
                try:
                    result = json.loads(message.content)
                except ValueError:
                    continue
                if not isinstance(result, dict) or result.get("success") is not True:
                    continue
                text = json.dumps({"success": True, "tool": message.name,
                                   "summary": str(result.get("content", ""))[:500]}, ensure_ascii=False)
            evidence.append({"id": message.message_id, "source": message.role.value, "text": text})
            evidence_by_id[message.message_id] = text
        if not evidence:
            self.service.apply(ShortTermMemoryPatch(action="NO_CHANGE"), source_by_id=source_by_id,
                               last_message_id=last_id)
            return "NO_CHANGE"
        logger.info("STM_MAINTAIN_START messages=%d version=%d", len(evidence), state.version)
        payload = {"current_state": state.model_dump(mode="json"), "new_messages": evidence,
                   "now": datetime.now(self.timezone).isoformat()}
        # A retry must stay small without forgetting the beginning of the recent window.
        fallback = (evidence if len(evidence) <= 16 else
                    [evidence[index * (len(evidence) - 1) // 15] for index in range(16)])
        diagnostic: dict = {}
        try:
            json_mode = True
            for attempt, batch in enumerate((evidence, fallback), start=1):
                payload["new_messages"] = batch
                options = {"max_tokens": 2400 if attempt == 1 else 4000, "temperature": 0}
                if json_mode:
                    options["response_format"] = {"type": "json_object"}
                try:
                    response = await self.provider.generate([
                        Message(role=Role.SYSTEM, content=MAINTAINER_PROMPT),
                        Message(role=Role.USER, content=json.dumps(payload, ensure_ascii=False, default=str)),
                    ], None, **options)
                except ProviderError as exc:
                    if attempt == 1 and exc.code == "provider_http_400" and json_mode:
                        json_mode = False
                        diagnostic = {"attempt": attempt, "provider_error_code": exc.code}
                        logger.warning("STM_JSON_MODE_REJECTED attempt=%d code=%s", attempt, exc.code)
                        continue
                    raise
                raw = response.content or ""
                diagnostic = {"attempt": attempt, "response_chars": len(raw),
                              "finish_reason": response.finish_reason}
                try:
                    patch = _parse_patch(raw)
                    break
                except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                    if isinstance(exc, json.JSONDecodeError):
                        diagnostic["error_position"] = exc.pos
                    logger.warning("STM_INVALID_RESPONSE attempt=%d chars=%d finish_reason=%s error_type=%s",
                                   attempt, len(raw), response.finish_reason, type(exc).__name__)
                    if attempt == 2:
                        raise
            self.service.apply(patch, source_by_id=source_by_id,
                               evidence_by_id=evidence_by_id, last_message_id=last_id)
            return self.service.last_maintenance["result"]
        except Exception as exc:
            logger.warning("STM_MAINTAIN_FAILED type=%s attempt=%s chars=%s finish_reason=%s",
                           type(exc).__name__, diagnostic.get("attempt"),
                           diagnostic.get("response_chars"), diagnostic.get("finish_reason"))
            try:
                self.service.record_failure(exc, details=diagnostic)
            except Exception as store_exc:
                logger.warning("STM_DIAGNOSTIC_SAVE_FAILED type=%s", type(store_exc).__name__)
            return "FAILED"
