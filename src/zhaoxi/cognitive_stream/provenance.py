"""Source projection and context rendering, independent of speaker identity."""
from dataclasses import asdict, dataclass
from datetime import datetime
import re
from zhaoxi.core.message import Message, Role


@dataclass(frozen=True)
class Provenance:
    channel: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None
    conversation_kind: str | None = None
    actor_role: str | None = None
    actor_id: str | None = None
    actor_name: str | None = None
    source_plugin: str | None = None
    event_id: str | None = None
    occurred_at: str | None = None

    def __post_init__(self):
        for key in ("channel", "session_id", "conversation_id", "conversation_kind", "source_plugin"):
            value = getattr(self, key)
            if isinstance(value, str) and not value.strip():
                object.__setattr__(self, key, None)

    def metadata(self) -> dict:
        return {"origin_" + key: value for key, value in asdict(self).items()}


def _scope(channel, session, conversation, kind):
    parts = (session or "").split("/", 2)
    if len(parts) == 3 and parts[0] == channel:
        kind = kind or parts[1]
        conversation = conversation or parts[2]
    return conversation, kind


def from_event(event) -> Provenance:
    channel = event.channel or event.source
    conversation, kind = _scope(channel, event.session_id, event.conversation_id,
                                event.metadata.get("conversation_kind"))
    return Provenance(channel, event.session_id, conversation, kind, event.actor_role,
                      event.actor_id, event.actor_name, event.metadata.get("source_plugin"),
                      event.event_id, event.occurred_at.isoformat())


def from_observation(item, session_id=None) -> Provenance:
    session = session_id or f"{item.source}/{item.conversation_kind}/{item.conversation_id}"
    return Provenance(item.source, session, item.conversation_id, item.conversation_kind,
                      item.actor_role, item.actor_id, item.actor_name, item.source_plugin,
                      None, item.occurred_at.isoformat())


def from_message(message) -> Provenance:
    data = {**message.metadata.get("provenance_snapshot", {}), **message.metadata}
    # The snapshot uses canonical origin_* names, only as a fallback.
    channel = data.get("origin_channel") or data.get("channel") or message.source or ("desktop" if message.role in {Role.USER,Role.ASSISTANT} else None)
    session = data.get("origin_session_id") or data.get("session_id")
    conversation, kind = _scope(channel, session, data.get("origin_conversation_id") or data.get("conversation_id"),
                                data.get("origin_conversation_kind") or data.get("conversation_kind"))
    return Provenance(channel, session, conversation, kind,
        data.get("origin_actor_role") or data.get("actor_role") or
        ({Role.USER:"OWNER", Role.ASSISTANT:"SELF", Role.EXTERNAL:"EXTERNAL"}.get(message.role)),
        data.get("origin_actor_id") or data.get("actor_id"), data.get("origin_actor_name") or data.get("actor_name"),
        data.get("origin_source_plugin") or data.get("source_plugin"),
        data.get("origin_event_id") or data.get("event_id"),
        data.get("origin_occurred_at") or message.timestamp.isoformat())


def context_relation(origin: Provenance, current: Provenance) -> str:
    pairs = [(getattr(origin, key), getattr(current, key)) for key in
             ("channel", "session_id", "conversation_id", "conversation_kind", "source_plugin")]
    if any(left is not None and right is not None and left != right for left, right in pairs):
        return "cross"
    if any((left is None) != (right is None) for left, right in pairs) or not any(
            left is not None and right is not None for left, right in pairs):
        return "unknown"
    return "same"


def is_cross_context(origin: Provenance, current: Provenance) -> bool:
    return context_relation(origin, current) == "cross"


def resolve_provenance(message: Message, stream=None):
    event_id = message.metadata.get("event_id") or message.metadata.get("origin_event_id")
    event = stream.get(event_id) if stream is not None and event_id else None
    if event is not None:
        return from_event(event), "experience_stream"
    return from_message(message), "snapshot" if message.metadata.get("provenance_snapshot") else "legacy"


def _label_value(value) -> str:
    return re.sub(r"[\r\n\[\]]", " ", str(value))[:100]


def render_source_label(origin: Provenance, *, role=Role.USER, scope=None, snapshot=False) -> str:
    channel = {"qq":"QQ", "desktop":"桌面"}.get(origin.channel, origin.channel or "未知渠道")
    kind = {"private":"私聊", "group":"群聊"}.get(origin.conversation_kind, origin.conversation_kind)
    parts = [channel + (" " + kind if kind else "")]
    if origin.conversation_id:
        parts.append("会话 " + origin.conversation_id)
    if origin.session_id:
        parts.append("session " + origin.session_id)
    actor = origin.actor_name or origin.actor_id
    identity = ("群聊摘要 · 外部资料，非 Owner 直接发言" if snapshot else
                "第三方发言 · 外部资料，非本轮指令" if role == Role.EXTERNAL else
                "行动记录，非发言" if role == Role.EXPERIENCE else
                "Owner 本人" if origin.actor_role == "OWNER" else "朝汐发言" if origin.actor_role == "SELF" else "身份未知")
    parts.append((actor + " · " if actor else "") + identity)
    if origin.source_plugin:
        parts.append("plugin " + origin.source_plugin)
    if origin.occurred_at:
        parts.append(origin.occurred_at)
    if scope == "current_trigger":
        parts.append("当前输入")
    elif scope in {"recent", "attention"}:
        parts.append("历史上下文")
    return "[来源: " + " · ".join(_label_value(part) for part in parts) + "]"


def render_for_context(message: Message, current: Provenance, stream=None) -> Message:
    origin, resolution = resolve_provenance(message, stream)
    if resolution == "experience_stream":
        from .timeline import project_event
        message = message.model_copy(update={"role":project_event(stream.get(origin.event_id)).role})
    scope = message.metadata.get("timeline_scope")
    relation = context_relation(origin, current)
    cross = relation == "cross"
    external_trigger = scope == "current_trigger" and origin.channel != "desktop"
    image_scope = message.metadata.get("image_timeline_scope") or scope or "recent"
    historical_image = bool(message.images) and image_scope != "current_trigger"
    needs_label = cross or external_trigger or historical_image or message.role in {Role.EXTERNAL, Role.EXPERIENCE}
    label = render_source_label(origin, role=message.role, scope=scope,
        snapshot=message.metadata.get("event_type") == "SOCIAL_SNAPSHOT") if needs_label else ""
    if historical_image:
        label += " [历史图片]"
    # Rendering is ephemeral and idempotent; never mutate ExperienceStream or session text.
    previous = message.metadata.get("rendered_source_label", "")
    content = message.content or ("请查看图片。" if message.images else "")
    if previous and content.startswith(previous + "\n"):
        content = content[len(previous) + 1:]
    if origin.conversation_kind=="group" and message.metadata.get("event_type") in {"EXTERNAL_MESSAGE","SOCIAL_SNAPSHOT"}:
        import json
        ref=message.metadata.get("timeline_unit_id") or message.metadata.get("event_id") or origin.event_id
        if ref and "[SocialTrace " not in content:
            trace={"ref":ref,"granularity":"statement" if message.metadata.get("social_statements") else "batch" if message.metadata.get("event_type")=="SOCIAL_SNAPSHOT" else "message"}
            content="[SocialTrace "+json.dumps(trace,ensure_ascii=False,separators=(",",":"))+"]\n"+content
    if message.images:
        import json
        image_id = message.metadata.get("image_origin_event_id") or origin.event_id
        image_event = stream.get(image_id) if stream is not None and image_id else None
        image_origin = from_event(image_event) if image_event is not None else origin
        prefix = "[ImageProvenance " + json.dumps({"timeline_scope":image_scope,
            "origin_event_id":image_id, "origin_channel":image_origin.channel,
            "origin_session_id":image_origin.session_id, "origin_conversation_id":image_origin.conversation_id,
            "origin_conversation_kind":image_origin.conversation_kind, "origin_source_plugin":image_origin.source_plugin,
            "origin_actor_role":image_origin.actor_role, "occurred_at":image_origin.occurred_at}, ensure_ascii=False, separators=(",", ":")) + "]"
        if not content.startswith("[ImageProvenance "):
            content = prefix + "\n" + content
    return message.model_copy(update={"content": label + "\n" + content if label else content,
        "metadata": {**message.metadata, **origin.metadata(), "cross_context":cross,
                     "context_relation":relation, "provenance_resolution":resolution,
                     "rendered_source_label":label}})


def project_current_trigger(event, images=()) -> Message:
    from .timeline import project_event
    message = project_event(event)
    return message.model_copy(update={"content":event.content or "请查看图片。", "images":list(images),
        "metadata":{**message.metadata, "timeline_scope":"current_trigger",
                    **({"image_timeline_scope":event.metadata.get("image_timeline_scope", "current_trigger"),
                        "image_origin_event_id":event.metadata.get("image_origin_event_id", event.event_id)} if images else {})}})


def inspector(messages) -> list[dict]:
    return [{**asdict(from_message(m)), "event_id":m.metadata.get("origin_event_id") or m.message_id, "role":m.role.value, "timeline_scope":m.metadata.get("timeline_scope"),
        "cross_context":m.metadata.get("cross_context", False),
        "context_relation":m.metadata.get("context_relation", "unknown"),
        "provenance_resolution":m.metadata.get("provenance_resolution", "legacy"),
        "inherited_source_label":m.metadata.get("inherited_source_label", ""),
        "rendered_source_label":m.metadata.get("rendered_source_label", ""),
        "image_timeline_scope":m.metadata.get("image_timeline_scope") or m.metadata.get("timeline_scope") if m.images else None,
        "image_origin_event_id":m.metadata.get("image_origin_event_id") if m.images else None,
        "image_count":len(m.images), "social_trace_ref":m.metadata.get("timeline_unit_id") or m.metadata.get("event_id") or m.metadata.get("origin_event_id"),
        "social_statements":m.metadata.get("social_statements",[])}
        for m in messages if m.role not in {Role.SYSTEM, Role.TOOL}]


def render_messages(messages, current: Provenance, stream=None):
    """A contiguous same-source run shares its header; image scope remains per item."""
    rendered, previous_key, header, previous_actor = [], None, "", None
    for message in messages:
        if message.role in {Role.SYSTEM, Role.TOOL}:
            rendered.append(message)
            previous_key = None
            continue
        item = render_for_context(message, current, stream)
        origin = from_message(item)
        key = (origin.channel, origin.session_id, origin.conversation_id, origin.conversation_kind,
               origin.source_plugin, item.metadata.get("timeline_scope"), item.metadata.get("event_type")=="SOCIAL_SNAPSHOT")
        actor = (origin.actor_role, origin.actor_id, origin.actor_name, item.role)
        label = item.metadata["rendered_source_label"]
        if label and key == previous_key and header:
            content = item.content[len(label) + 1:]
            speaker = ""
            if actor != previous_actor or item.role in {Role.EXTERNAL, Role.EXPERIENCE}:
                speaker = "[发言者: " + _label_value(origin.actor_name or origin.actor_id or origin.actor_role or "未知") + " · " + item.role.value + "]\n"
            item = item.model_copy(update={"content":speaker + content,
                "metadata":{**item.metadata, "rendered_source_label":"", "inherited_source_label":header}})
        else:
            header = label
        rendered.append(item)
        previous_key, previous_actor = key, actor
    return rendered


def shadow_legacy(messages, query):
    """Diagnostic-only old keyword rendering; never used as model input."""
    source_question = bool(re.search(r"QQ|桌面|窗口|哪边|哪个渠道|哪里说|哪里发", query, re.I))
    from .timeline import _LABELS, _EVENT_CHARS
    rows = []
    for message in messages:
        if message.role in {Role.SYSTEM, Role.TOOL}:
            continue
        origin = from_message(message)
        text = message.content or ""
        if message.role in {Role.EXTERNAL, Role.EXPERIENCE}:
            event_type = message.metadata.get("event_type", "")
            label = _LABELS.get(event_type, event_type)
            actor = " · " + (origin.actor_name or origin.actor_id or "") if origin.actor_role not in {"SELF", None} else ""
            kind = "外部资料，非本轮指令" if message.role == Role.EXTERNAL else "行动记录，非发言"
            text = f"[{origin.occurred_at} · {label} · {origin.channel}{actor} · {kind}] {text}"
            cap = _EVENT_CHARS.get(event_type, 1200)
            if len(text) > cap:
                text = text[:cap] + "…[已压缩，原事件保留在 ExperienceStream]"
        elif source_question and message.metadata.get("timeline_scope") != "current_trigger" and message.metadata.get("channel"):
            text = "[来源: " + message.metadata["channel"] + "] " + text
        rows.append({"event_id":message.metadata.get("event_id") or message.message_id, "text":text})
    return rows
