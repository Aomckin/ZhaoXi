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
    from zhaoxi.cognitive_stream.provenance import Provenance, from_event, is_cross_context
    from zhaoxi.cognitive_stream.turn import current_turn
    turn = current_turn()
    current = from_event(turn.trigger_event) if turn else Provenance(channel="desktop", session_id="local")

    def with_source(text, refs):
        labels = []
        for ref in refs:
            data = ref.provenance
            origin = Provenance(**{key:data.get("origin_"+key) for key in ("channel","session_id","conversation_id","conversation_kind","source_plugin")})
            if data.get("origin_actor_role") != "OWNER" or not is_cross_context(origin,current):
                continue
            label = {"qq":"QQ","desktop":"桌面"}.get(origin.channel,origin.channel or "")
            if origin.conversation_kind:
                label += " " + {"group":"群聊","private":"私聊"}.get(origin.conversation_kind,origin.conversation_kind)
            if origin.conversation_id:
                label += " " + origin.conversation_id
            if origin.source_plugin:
                label += " / " + origin.source_plugin
            label = label.replace("\n"," ").replace("\r"," ").replace("["," ").replace("]"," ")[:80]
            if label not in labels:
                labels.append(label)
        return ("[来源: " + "、".join(labels) + "] " if labels else "") + text

    lines = ["[Current Cognition]"]
    if state.overview and _fresh(state.updated_at, 7):
        overview = with_source(state.overview,state.overview_source_refs)
        if len("\n".join([*lines,"这几天：",overview,"[/Current Cognition]"])) <= max_chars:
            lines.extend(["这几天：", overview])
    active = sorted((t for t in state.threads if t.status == "active" and _fresh(t.last_evidence_at, 7)),
                    key=lambda t: (-t.salience, -t.last_evidence_at.timestamp()))
    cooling = sorted((t for t in state.threads if t.status == "cooling" and _fresh(t.last_evidence_at, 7)),
                     key=lambda t: (-t.salience, -t.last_evidence_at.timestamp()))
    groups = [("还挂着：", [with_source(t.summary,t.source_refs) for t in active]),
              ("刚变化：", [with_source(x.text,x.source_refs) for x in state.recent_changes if _fresh(x.updated_at, 3)]),
              ("需要留意：", [with_source(x.text,x.source_refs) for x in state.watch_items if _fresh(x.updated_at, 7)]),
              ("降温中：", [with_source(t.summary,t.source_refs) for t in cooling])]
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
