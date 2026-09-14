"""Explicit, bounded temporal metadata for requests that need time reasoning."""

from __future__ import annotations

import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from zhaoxi.core.conversation import Conversation
from zhaoxi.core.message import Role


_TEMPORAL_QUESTION = re.compile(
    r"(?:什么时候|几点|多久|多长时间|持续多久|从.+到|之间|先后|时间线|哪天|日期|"
    r"跨天|连续.{0,8}(?:小时|分钟|天)|how long|when|timeline)",
    re.IGNORECASE,
)
_TEMPORAL_SCOPE = re.compile(
    r"(?:今天|昨天|昨晚|前天|明天|后天|当时|那天|半夜|凌晨|早上|上午|中午|下午|晚上|"
    r"\d{1,2}[点时]|\d{4}[-/]\d{1,2}[-/]\d{1,2})"
)
_SCOPED_TASK = re.compile(r"(?:查|看|回顾|复盘|记录|发生|做了|吃了|睡|工作|游戏|状态|怎么样|如何|判断|推断)")


def needs_temporal_context(conversation: Conversation) -> bool:
    """Use timestamps only when the current user request explicitly needs them."""
    current = next(
        (item.content or "" for item in reversed(conversation.messages) if item.role == Role.USER),
        "",
    )
    return bool(_TEMPORAL_QUESTION.search(current) or (_TEMPORAL_SCOPE.search(current) and _SCOPED_TASK.search(current)))


def build_temporal_context(
    conversation: Conversation,
    *,
    timezone: ZoneInfo,
    now: datetime,
    limit: int = 12,
) -> str | None:
    if not needs_temporal_context(conversation):
        return None
    observations = [
        {
            "message_index": index,
            "role": item.role.value,
            "observed_at": item.timestamp.astimezone(timezone).isoformat(timespec="seconds"),
            "observation_kind": "point",
        }
        for index, item in enumerate(conversation.recent(limit))
        if item.role in {Role.USER, Role.ASSISTANT} and item.content
    ]
    payload = {
        "current_time": now.isoformat(timespec="seconds"),
        "timezone": str(timezone),
        "message_observations": observations,
    }
    return (
        "\n\n[Temporal Context]\n"
        "仅用于当前请求的时间推理；这是元数据，不是对话正文，不得复述标签或 JSON。\n"
        "硬约束：每条聊天时间只能视为一个离散 point observation，只能证明该时点发生过消息交换；"
        "禁止由两个消息时点推断中间持续清醒、工作、游戏、睡眠或任何 interval/state。\n"
        "event_at 表示有证据支持的事件发生时间；recorded_at/known_at 仅表示记录或获知时间。"
        "缺少 event_at 时不得把 recorded_at、known_at 或消息 timestamp 当成事件发生时间。\n"
        "模型或 Agent 在某时点拥有一条信息，不代表 Agent 当时存在、在场或亲历该事件；"
        "导入日记、Archive 与 Memory 的时间不得用于推断 Agent presence。\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + "\n[/Temporal Context]"
    )
