"""Build a bounded chronological recent-experience view from ExperienceStream."""
from datetime import UTC, datetime, timedelta
import json
from hashlib import sha1
from collections import defaultdict

from zhaoxi.core.message import Message, Role
from .models import CognitiveEvent, CognitiveEventType, EpisodeSummary
from .store import ExperienceStream
from .provenance import from_event

RECENT_HOURS = 1.5
RECENT_LIMIT = 48
RECENT_MAX_CHARS = 14000

_LABELS = {
    CognitiveEventType.EXTERNAL_MESSAGE: "外部发言",
    CognitiveEventType.SOCIAL_SNAPSHOT: "群聊摘要",
    CognitiveEventType.TOOL_ACTION: "工具行动",
    CognitiveEventType.TOOL_OBSERVATION: "工具结果",
    CognitiveEventType.WORKFLOW_EVENT: "流程结果",
    CognitiveEventType.PLANNER_EVENT: "规划结果",
    CognitiveEventType.PROACTIVE_EVENT: "主动发言",
    CognitiveEventType.SYSTEM_EVENT: "运行状态",
    CognitiveEventType.SELF_EVENT: "自身行动",
}
_EVENT_CHARS = {
    CognitiveEventType.TOOL_OBSERVATION: 480,
    CognitiveEventType.SOCIAL_SNAPSHOT: 600,
    CognitiveEventType.SYSTEM_EVENT: 240,
    CognitiveEventType.PLANNER_EVENT: 300,
}


def visible_event(event: CognitiveEvent, output_channel: str, audience: str,
                  public_session_id: str | None = None) -> bool:
    """Apply output privacy; source/channel never determines cognitive identity."""
    if not event.content and not event.parts:
        return False
    if output_channel == "desktop":
        return True
    if audience != "owner":
        return event.privacy_level == "SOCIAL" and event.session_id == public_session_id
    if event.privacy_level == "LOCAL_ONLY":
        return False
    return True


def project_event(event: CognitiveEvent) -> Message:
    """Preserve Owner and assistant speech as roles; label other events as facts."""
    if event.event_type == CognitiveEventType.ASSISTANT_REPLY:
        role = Role.ASSISTANT
    elif event.event_type in {CognitiveEventType.USER_MESSAGE,
                             CognitiveEventType.EXTERNAL_MESSAGE} and event.actor_role == "OWNER":
        role = Role.USER
    elif event.event_type == CognitiveEventType.PROACTIVE_EVENT:
        role = Role.ASSISTANT
    elif event.event_type in {CognitiveEventType.EXTERNAL_MESSAGE,
                               CognitiveEventType.SOCIAL_SNAPSHOT}:
        role = Role.EXTERNAL
    else:
        role = Role.EXPERIENCE
    content = event.content or ""
    images = [part.url for part in event.parts if part.type == "image" and
              part.url and part.url.startswith("data:image/")]
    if any(part.type == "image" for part in event.parts) and not images:
        content += "\n[这条历史事件的图片本体不可用，只能依据已有文字描述，不能推断具体视觉细节。]"
    cap = _EVENT_CHARS.get(event.event_type, 1200 if role in {Role.EXTERNAL, Role.EXPERIENCE} else 2400)
    if len(content) > cap:
        content = content[:cap] + "…[已压缩，原事件保留在 ExperienceStream]"
    return Message(
        message_id=event.event_id,
        role=role,
        content=content,
        images=images,
        source=event.source,
        timestamp=event.occurred_at,
        metadata={
            "provenance_snapshot":from_event(event).metadata(),
            "event_id": event.event_id,
            "social_statements":event.metadata.get("social_statements",[]),
            "trace_granularity":event.metadata.get("trace_granularity"),
            "event_type": event.event_type.value,
            "channel": event.channel,
            "session_id": event.session_id,
            "actor_role": event.actor_role,
            "privacy_level": event.privacy_level,
            "trust_level": event.trust_level,
            "parent_refs": list(event.parent_refs),
            "turn_id": event.turn_id,
            "reply_to_event_id": event.reply_to_event_id,
            "caused_by_event_id": event.caused_by_event_id,
        },
    )


def _ambient_key(event: CognitiveEvent) -> str | None:
    if (event.event_type == CognitiveEventType.EXTERNAL_MESSAGE
        and event.actor_role != "OWNER"
        and event.metadata.get("conversation_kind") == "group"
        and not event.metadata.get("directed_to_zhaoxi")):
        bucket = int(event.occurred_at.timestamp()) // 600
        return f"ambient:{event.session_id or event.conversation_id}:{event.metadata.get('source_plugin') or 'unknown'}:{bucket}"
    return None


def _causal_units(events: list[CognitiveEvent]) -> list[list[CognitiveEvent]]:
    """Group interleaved input/reply/action events by causal turn, then sort turns."""
    by_id = {event.event_id: event for event in events}
    def root(event: CognitiveEvent) -> str:
        ambient = _ambient_key(event)
        if ambient:
            return ambient
        if event.turn_id:
            return event.turn_id
        cursor = event
        seen = set()
        while cursor.event_id not in seen:
            seen.add(cursor.event_id)
            parent_id = cursor.reply_to_event_id or cursor.caused_by_event_id or (
                cursor.parent_refs[0] if cursor.parent_refs else None)
            if not parent_id or parent_id not in by_id:
                break
            cursor = by_id[parent_id]
            if cursor.turn_id:
                return cursor.turn_id
        return cursor.event_id
    groups: dict[str, list[CognitiveEvent]] = defaultdict(list)
    for event in events:
        groups[root(event)].append(event)
    def within(event: CognitiveEvent) -> tuple:
        priority = (0 if event.event_type in {CognitiveEventType.USER_MESSAGE,
                    CognitiveEventType.EXTERNAL_MESSAGE} else
                    2 if event.event_type in {CognitiveEventType.ASSISTANT_REPLY,
                    CognitiveEventType.PROACTIVE_EVENT} else 1)
        return (priority, event.occurred_at, event.event_id)
    units = [sorted(group, key=within) for group in groups.values()]
    return sorted(units, key=lambda unit: (min(e.occurred_at for e in unit), unit[0].event_id))


def _unit_payload(events: list[CognitiveEvent]) -> dict:
    root = _ambient_key(events[0]) or events[0].turn_id or events[0].event_id
    statements = events[0].metadata.get("social_statements", [])
    if _ambient_key(events[0]) and not statements:
        statements = [{"statement_id": f"s{i+1}", "text": (event.content or "[图片]")[:100],
                       "source_event_ids": [event.event_id]} for i, event in enumerate(events[:3])]
    return {
        "unit_id": root if root.startswith("ambient:") else "turn:" + root,
        "turn_id": None if _ambient_key(events[0]) else events[0].turn_id,
        "source_event_ids": [event.event_id for event in events],
        "parent_refs": list(dict.fromkeys(ref for event in events for ref in event.parent_refs)),
        "raw_refs": list(dict.fromkeys(ref for event in events for ref in event.source_refs)),
        "occurred_at": min(event.occurred_at for event in events).isoformat(),
        "level": "L1",
        "social_statements": statements,
    }


def summarize_episode(events: list[CognitiveEvent]) -> EpisodeSummary:
    """Minimal L2 summary, always retaining the raw-event resolution path."""
    if not events:
        raise ValueError("episode requires events")
    ordered = sorted(events, key=lambda event: (event.occurred_at, event.event_id))
    digest = sha1("|".join(event.event_id for event in ordered).encode()).hexdigest()[:16]
    return EpisodeSummary(
        episode_id="episode:" + digest,
        content=f"{len(ordered)} 条较早经历：" + "；".join(
            f"[s{i+1}] {event.actor_name or event.actor_role or '事件'}：{(event.content or '[图片]')[:80]}"
            for i,event in enumerate(ordered[:3])),
        source_event_ids=[event.event_id for event in ordered],
        parent_refs=list(dict.fromkeys(ref for event in ordered for ref in event.parent_refs)),
        source_refs=list(dict.fromkeys(ref for event in ordered for ref in event.source_refs)),
        occurred_at=ordered[0].occurred_at,
    )


def cognitive_timeline(
    stream: ExperienceStream,
    *,
    query: str = "",
    output_channel: str = "desktop",
    audience: str = "owner",
    attention=None,
    trigger_id: str | None = None,
    public_session_id: str | None = None,
    limit: int = RECENT_LIMIT,
    max_chars: int = RECENT_MAX_CHARS,
    recent_hours: float = RECENT_HOURS,
) -> list[Message]:
    """L1 recent causal timeline plus L2 older recall; current trigger is separate."""
    cutoff = datetime.now(UTC) - timedelta(hours=recent_hours)
    candidates = [event for event in stream.recent(max(300, limit * 6))
                  if event.occurred_at >= cutoff and event.event_id != trigger_id
                  and visible_event(event, output_channel, audience, public_session_id)]
    trigger = stream.get(trigger_id) if trigger_id else None
    active_turn = trigger.turn_id if trigger else None
    # Current-turn tool/planner records are represented by the active provider transcript.
    candidates = [event for event in candidates if not active_turn or event.turn_id != active_turn]
    snapshot_refs = {ref for event in candidates if event.event_type == CognitiveEventType.SOCIAL_SNAPSHOT
                     for ref in event.source_refs + event.parent_refs}
    candidates = [event for event in candidates if not (
        event.event_type == CognitiveEventType.EXTERNAL_MESSAGE and event.actor_role != "OWNER"
        and any(ref in snapshot_refs for ref in event.source_refs))]
    units = _causal_units(candidates)
    selected: list[list[Message]] = []
    chars = 0
    count = 0
    for events in reversed(units):
        payload = _unit_payload(events)
        projected = []
        if len(events) > 1 and _ambient_key(events[0]):
            excerpts = [f"[s{i+1}] {e.actor_name or e.actor_id or '群友'}：{(e.content or '[图片]')[:100]}"
                        for i,e in enumerate(events[:3])]
            summary = f"[{events[0].occurred_at.isoformat()} · 群聊记录 · {events[0].channel}] "
            summary += f"这段时间有 {len(events)} 条发言；" + "；".join(excerpts)
            if len(events) > 3:
                summary += "；其余原文可通过 Timeline Unit 回查。"
            message = Message(role=Role.EXTERNAL, content=summary[:650],
                              message_id=payload["unit_id"], timestamp=events[0].occurred_at,
                              source=events[0].source,
                              metadata={"provenance_snapshot":from_event(events[0]).metadata(), "event_type":"SOCIAL_SNAPSHOT",
                                        "timeline_scope": "recent", "timeline_unit_id": payload["unit_id"],
                                        "source_event_ids": payload["source_event_ids"], "social_statements":payload["social_statements"],
                                        "privacy_level": events[0].privacy_level})
            projected.append(message)
        else:
            for event in events:
                message = project_event(event)
                message.metadata.update({"timeline_scope": "recent", "timeline_unit_id": payload["unit_id"],
                                         "source_event_ids": payload["source_event_ids"]})
                projected.append(message)
        size = sum(len(message.content or "") for message in projected)
        if (chars + size > max_chars or count + len(projected) > limit) and selected:
            continue
        selected.append(projected)
        chars += size
        count += len(projected)
        stream.save_timeline_unit(payload["unit_id"], json.dumps(payload, ensure_ascii=False))
        if count >= limit:
            break
    recent = [message for group in reversed(selected) for message in group]
    if attention is not None and query and chars < max_chars:
        focused = attention.retrieve(
            query, trigger_id=trigger_id, older_than=cutoff,
            include_private=(output_channel == "desktop" or audience == "owner"),
            limit=8, max_chars=min(3000, max_chars - chars),
        )
        known = {event.event_id for event in candidates}
        ambient_recall = [event for event in focused.events if _ambient_key(event) and
                          event.event_id not in known and event.event_id != trigger_id and
                          visible_event(event, output_channel, audience, public_session_id)]
        compressed_ids = set()
        scope_groups = defaultdict(list)
        for event in ambient_recall:
            origin = from_event(event)
            scope_groups[(origin.channel,origin.session_id,origin.conversation_id,
                          origin.conversation_kind,origin.source_plugin)].append(event)
        for group in scope_groups.values():
            if len(group) < 3:
                continue
            episode = summarize_episode(group)
            payload = {"unit_id": episode.episode_id, "level": "L2",
                       "source_event_ids": episode.source_event_ids,
                       "parent_refs": episode.parent_refs, "raw_refs": episode.source_refs,
                       "occurred_at": episode.occurred_at.isoformat(),
                       "social_statements":[{"statement_id":f"s{i+1}","text":(event.content or "[图片]")[:80],"source_event_ids":[event.event_id]} for i,event in enumerate(group[:3])]}
            stream.save_timeline_unit(episode.episode_id, json.dumps(payload, ensure_ascii=False))
            recent.insert(0, Message(message_id=episode.episode_id, role=Role.EXTERNAL,
                content=episode.content, timestamp=episode.occurred_at,
                metadata={"provenance_snapshot":from_event(group[0]).metadata(), "event_type":"SOCIAL_SNAPSHOT",
                          "timeline_scope": "attention", "timeline_unit_id": episode.episode_id,
                          "source_event_ids": episode.source_event_ids, "social_statements":payload["social_statements"]}))
            compressed_ids.update(episode.source_event_ids)
            chars += len(episode.content)
        for event in focused.events:
            if event.event_id in compressed_ids:
                continue
            if event.event_id in known or event.event_id == trigger_id or not visible_event(
                    event, output_channel, audience, public_session_id):
                continue
            message = project_event(event)
            if chars + len(message.content or "") > max_chars:
                continue
            message.metadata["timeline_scope"] = "attention"
            recent.insert(0, message)
            chars += len(message.content or "")
    return recent
