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


def decode_main_reply(response: ModelResponse, *, fast: bool = False) -> ModelResponse:
    if response.tool_calls:
        return response
    raw = (response.content or "").strip()
    if raw.startswith("```json") and raw.endswith("```"):
        raw = raw[7:-3].strip()
    try:
        arguments = json.loads(raw)
    except ValueError:
        # Salvage completed reply text from a truncated metadata envelope;
        # metadata must not become a prerequisite or leak onto the chat surface.
        match = re.search(r'"reply"\s*:\s*(")', raw)
        if raw.startswith("{") and match:
            try:
                value, _ = json.JSONDecoder().raw_decode(raw[match.start(1):])
                if isinstance(value, str):
                    return response.model_copy(update={"content":value})
            except ValueError:
                pass
            return response.model_copy(update={"content":"模型回复未能完整解析，请重试。"})
        return response
    if not isinstance(arguments, dict) or "reply" not in arguments:
        return response
    if fast and isinstance(arguments.get("escalation"), dict):
        return response.model_copy(update={
            "content":"[escalate:" + json.dumps(arguments["escalation"],ensure_ascii=False) + "]"})
    content = arguments.get("reply")
    if not isinstance(content, str) or not content.strip():
        content = "模型没有返回可显示的内容。"
    try:
        awareness = DecisionAwarenessTrace.from_reply(arguments.get("awareness"))
        if awareness.mode.value != "NONE" or awareness.feedback:
            content += "<decision-awareness>" + awareness.model_dump_json() + "</decision-awareness>"
    except ValueError:
        # A metadata failure never blocks valid text or asks another model.
        logging.getLogger("DECISION").warning("main reply has invalid awareness metadata")
    return response.model_copy(update={"content":content})
