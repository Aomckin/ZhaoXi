"""Compact, natural, always-on model context."""

from __future__ import annotations

from .models import Category, ShortTermMemoryState, Status


LABELS = {
    Category.ACTIVE_CONTEXT: "近期背景",
    Category.ACTIVE_THREAD: "持续推进",
    Category.RECENT_TOPIC: "近期话题",
    Category.RECENT_CHANGE: "近期变化",
    Category.UNRESOLVED: "仍需关注",
}


def render(state: ShortTermMemoryState) -> str:
    lines = ["[Short-Term Memory]"]
    if not state.overview and not state.items:
        return "[Short-Term Memory]\n近期上下文尚未形成。"
    if state.overview:
        lines.append(state.overview.strip())
    covered = set(state.overview.rstrip("。").split("；")) if state.overview else set()
    for category, label in LABELS.items():
        entries = [item.content for item in state.items
                   if item.category == category and item.status == Status.ACTIVE
                   and item.confidence >= 0.7
                   and item.content not in covered
                   and (category != Category.RECENT_TOPIC or len(set(item.source_message_ids)) >= 2)]
        if entries:
            lines.append(f"{label}：" + "；".join(entries[:6]) + "。")
    if len(lines) == 1:
        lines.append("近期上下文正在形成。")
    return "\n".join(lines)[:2200]
