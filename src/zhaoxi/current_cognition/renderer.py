"""Bounded journal views for model, desk and diagnostics."""
from __future__ import annotations
from datetime import UTC, datetime, timedelta
from .models import CurrentCognitionState

def _fresh(at: datetime | None, days: int) -> bool:
    if at is None:
        return True
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return datetime.now(UTC) - at < timedelta(days=days)

def render_for_fast_chat(state: CurrentCognitionState, *, max_chars: int = 350) -> str:
    lines = ["[Current Cognition]"]
    if state.overview and _fresh(state.updated_at, 7):
        lines.extend(["这几天：", state.overview])
    active = sorted((t for t in state.threads if t.status == "active" and _fresh(t.last_evidence_at, 7)),
                    key=lambda t: (-t.salience, -t.last_evidence_at.timestamp()))
    cooling = sorted((t for t in state.threads if t.status == "cooling" and _fresh(t.last_evidence_at, 7)),
                     key=lambda t: (-t.salience, -t.last_evidence_at.timestamp()))
    groups = [("还挂着：", [t.summary for t in active]),
              ("刚变化：", [x.text for x in state.recent_changes if _fresh(x.updated_at, 3)]),
              ("需要留意：", [x.text for x in state.watch_items if _fresh(x.updated_at, 7)]),
              ("降温中：", [t.summary for t in cooling])]
    for heading, values in groups:
        added = False
        for value in values:
            proposed = "\n".join([*lines, *(([heading] if not added else [])), "- " + value, "[/Current Cognition]"])
            if len(proposed) > max_chars:
                continue
            if not added:
                lines.append(heading)
                added = True
            lines.append("- " + value)
    if len(lines) == 1:
        lines.append("近期状态尚未形成。")
    return "\n".join([*lines, "[/Current Cognition]"])

def render_for_desk(state: CurrentCognitionState) -> dict:
    return {"overview": state.overview if _fresh(state.updated_at, 7) else "",
            "sections": {"active_thread": [t.summary for t in state.threads if t.status == "active" and _fresh(t.last_evidence_at, 7)],
                         "recent_change": [item.text for item in state.recent_changes if _fresh(item.updated_at, 3)],
                         "unresolved": [item.text for item in state.watch_items if _fresh(item.updated_at, 7)]},
            "updated_at": state.updated_at.isoformat() if state.updated_at else None}

def render_for_debug(state: CurrentCognitionState) -> dict:
    return state.model_dump(mode="json")

render = render_for_fast_chat
