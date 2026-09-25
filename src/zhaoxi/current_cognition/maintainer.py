"""Inspect each finished turn without delaying or changing the main reply."""

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
from .service import CurrentCognitionPatch, CurrentCognitionService

logger = logging.getLogger("CURRENT_COGNITION")


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
        self.service = service
        self.provider = provider
        self.timezone = ZoneInfo(timezone)

    async def maintain(self, messages: list[Message], *, pending_override: list[Message] | None = None,
                       background: bool = False) -> str:
        state = self.service.state()
        if not messages and not pending_override:
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
        source_by_id: dict[str, str] = {}
        evidence_by_id: dict[str, str] = {}
        for message in pending:
            if message.role not in {Role.USER, Role.ASSISTANT} or not message.content:
                continue
            source_by_id[message.message_id] = message.role.value
            content = message.content[:1200 if message.role == Role.USER else 350]
            evidence_by_id[message.message_id] = content
            evidence.append({"id": message.message_id, "source": message.role.value, "text": content})
        if not any(item["source"] == "user" for item in evidence):
            self.service.apply(CurrentCognitionPatch(decision="NO_CHANGE"), source_by_id=source_by_id,
                               last_message_id=last_id, allow_empty_cursor=True)
            return "NO_CHANGE"
        logger.info("COGNITION_MAINTAIN_START messages=%d version=%d", len(evidence), state.version)
        payload = {"current_state": state.model_dump(mode="json"), "new_messages": evidence,
                   "now": datetime.now(self.timezone).isoformat()}
        if background:
            payload["task"] = "BOOTSTRAP" if not state.narrative else "BACKGROUND_CONSOLIDATION"
            payload["observation_buffer"] = [item.model_dump(mode="json") for item in state.observations]
        if not state.narrative and state.last_processed_message_id is None:
            payload["legacy_reference_untrusted"] = self.service.store.legacy_reference()
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
                    logger.warning("COGNITION_INVALID_RESPONSE attempt=%d chars=%d type=%s field=%s",
                                   attempt, len(raw), type(exc).__name__, diagnostic["field_path"])
                    if attempt == 2:
                        raise
            self.service.apply(patch, source_by_id=source_by_id,
                               evidence_by_id=evidence_by_id, last_message_id=last_id)
            if not self.service.state().narrative and background:
                return "PENDING_BOOTSTRAP"
            if self.service.last_maintenance.get("rejection"):
                return "REJECTED"
            return self.service.last_maintenance["decision"]
        except Exception as exc:
            logger.warning("COGNITION_MAINTAIN_FAILED type=%s attempt=%s", type(exc).__name__,
                           diagnostic.get("attempt"))
            try:
                self.service.record_failure(exc, details=diagnostic)
            except Exception as store_exc:
                logger.warning("COGNITION_DIAGNOSTIC_SAVE_FAILED type=%s", type(store_exc).__name__)
            return "FAILED"
