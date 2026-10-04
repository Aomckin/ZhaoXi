"""Serialize the main reply and its awareness in one response, without a tool."""

import json
import logging
import re
from pydantic import BaseModel, Field

from zhaoxi.models.types import ModelResponse
from .models import DecisionAwarenessTrace


class MainReply(BaseModel):
    reply: str = Field(description="自然最终台词。PICK 给一个答案收住；ADVISE 先建议短原因；FRAME 事实、冲突、最后个人价值判断。FAST 升级时留空。")
    awareness: DecisionAwarenessTrace = Field(description="同一主回复的旁产物。凡给选择建议用 PICK/ADVISE/FRAME；只有无选择的闲聊/反思用 NONE。不可伪造参考资料或授权。")
    escalation: dict | None = Field(default=None,
        description="仅 FAST 缺必要资料时填 kind=decision/recall/tool, reason, trigger_span（本轮逐字原文），不夹带草稿；STANDARD 不填。")


REPLY_FORMAT = {"type":"json_schema","json_schema":{
    "name":"main_reply","schema":MainReply.model_json_schema()}}


def _finish(response: ModelResponse, body: str, *, encoding: str,
            awareness: str = "missing", mode: str | None = None,
            content: str | None = None, error_code: str | None = None) -> ModelResponse:
    """Record protocol shape and sizes only, never private text or reasoning."""
    protocol = {"encoding": encoding, "input_chars": len(response.content or ""),
                "body_chars": len(body.strip()), "awareness": awareness,
                "mode": mode, "status": "failed" if error_code else "decoded",
                "error_code": error_code}
    from zhaoxi.observability import current_trace
    if trace := current_trace():
        trace.emit("main_reply_protocol", "response_generation",
                   "failed" if error_code else "warning" if awareness == "invalid" else "info",
                   "模型未返回可交付正文" if error_code else "已核对主回复格式",
                   error_code=error_code, metadata=protocol)
    if error_code:
        from zhaoxi.errors import AgentLoopError
        logging.getLogger("DECISION").warning("main reply rejected: %s", protocol)
        raise AgentLoopError("模型没有返回可显示的正文或回复格式不完整，请重试。", code=error_code)
    return response.model_copy(update={"content": body if content is None else content,
        "raw_metadata": {**response.raw_metadata, "main_reply_protocol": protocol}})


def decode_main_reply(response: ModelResponse, *, fast: bool = False) -> ModelResponse:
    if response.tool_calls:
        return response
    raw = (response.content or "").strip()
    if not raw:
        return _finish(response, "", encoding="empty", error_code="empty_model_reply")
    if raw.startswith("```json") and raw.endswith("```"):
        raw = raw[7:-3].strip()
    try:
        arguments = json.loads(raw)
    except ValueError:
        # Recover only a complete reply string, never unfinished/private metadata.
        match = re.search(r'"reply"\s*:\s*(")', raw)
        if raw.startswith("{") and match:
            try:
                value, _ = json.JSONDecoder().raw_decode(raw[match.start(1):])
                if isinstance(value, str) and value.strip():
                    return _finish(response, value, encoding="truncated_json", awareness="invalid")
            except ValueError:
                pass
            return _finish(response, "", encoding="truncated_json", error_code="invalid_reply_protocol")
        if raw.startswith("{") and re.search(r'"(?:awareness|escalation)"\s*:', raw):
            return _finish(response, "", encoding="truncated_json", error_code="invalid_reply_protocol")
        return _finish(response, raw, encoding="text")
    if not isinstance(arguments, dict) or "reply" not in arguments:
        if isinstance(arguments, dict) and any(key in arguments for key in ("awareness", "escalation")):
            return _finish(response, "", encoding="json", error_code="invalid_reply_protocol")
        return _finish(response, raw, encoding="text")
    if fast and isinstance(arguments.get("escalation"), dict):
        return _finish(response, "", encoding="fast_escalation", content=
            "[escalate:" + json.dumps(arguments["escalation"], ensure_ascii=False) + "]")
    body = arguments.get("reply")
    if not isinstance(body, str) or not body.strip():
        return _finish(response, "", encoding="json", error_code="empty_model_reply")
    content, awareness_state, mode = body, "missing", None
    if arguments.get("awareness") is not None:
        try:
            awareness = DecisionAwarenessTrace.from_reply(arguments["awareness"])
            awareness_state, mode = "valid", awareness.mode.value
            if mode != "NONE" or awareness.feedback or awareness.follow_up_asked_id:
                content += "<decision-awareness>" + awareness.model_dump_json() + "</decision-awareness>"
        except ValueError:
            awareness_state = "invalid"
            logging.getLogger("DECISION").warning("main reply has invalid awareness metadata")
    return _finish(response, body, encoding="json", awareness=awareness_state, mode=mode, content=content)
