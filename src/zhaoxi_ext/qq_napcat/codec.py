"""OneBot 11 message decoding; meta and notice events are transport events."""
from datetime import UTC, datetime
from zhaoxi.perception.models import AttentionHint, Observation, ObservationPart, TrustLevel


def decode(event: dict, *, self_id: str | None, owner_id: str = "") -> Observation | None:
    if event.get("post_type") != "message":
        return None
    kind = event.get("message_type")
    if kind not in ("group", "private"):
        return None
    sender = event.get("sender") or {}
    bot_markers = (event.get("is_bot"), event.get("sender_is_bot"),
                   sender.get("is_bot"), sender.get("bot"))
    sender_is_bot = any(value is True or value == 1 or str(value).lower() == "true"
                        for value in bot_markers) or str(sender.get("role") or "").lower() == "bot"
    actor_id = str(event.get("user_id") or sender.get("user_id") or "")
    own = bool(self_id and actor_id == str(self_id)) or bool(event.get("self_message"))
    owner = bool(owner_id and actor_id == owner_id)
    conversation_id = str(event.get("group_id") if kind == "group" else actor_id)
    if not conversation_id or conversation_id == "None":
        return None
    segments = event.get("message") or []
    if isinstance(segments, str):
        segments = [{"type": "text", "data": {"text": segments}}]
    text, attachments, parts = [], [], []
    directed = False
    reply_to = None
    for part in segments:
        if not isinstance(part, dict):
            continue
        data = part.get("data") or {}
        typ = part.get("type")
        if typ == "text":
            value = str(data.get("text") or "")
            text.append(value)
            parts.append(ObservationPart(type="text", text=value))
        elif typ == "at":
            qq = str(data.get("qq") or "")
            if self_id and qq == str(self_id):
                directed = True
            text.append("@" + qq)
            parts.append(ObservationPart(type="mention", target=qq))
        elif typ == "reply":
            reply_to = str(data.get("id") or "")
            parts.append(ObservationPart(type="reply", target=reply_to))
        elif typ == "image":
            attachments.append({"type": "image", "url": data.get("url"), "file": data.get("file")})
            parts.append(ObservationPart(type="image", url=data.get("url"), file=data.get("file")))
    content = "".join(text).strip()[:20000]
    if kind == "group" and (content.startswith("朝汐") or content.startswith("@朝汐")):
        directed = True
    message_id = str(event.get("message_id") or "")
    if not message_id:
        return None
    occurred = datetime.fromtimestamp(float(event.get("time") or datetime.now(UTC).timestamp()), UTC)
    return Observation(source="qq", source_plugin="qq_napcat", source_kind=kind + "_message", actor_id=actor_id,
        actor_name=sender.get("card") or sender.get("nickname") or None,
        actor_role="OWNER" if owner else "EXTERNAL", conversation_id=conversation_id,
        conversation_kind=kind, content=content, attachments=attachments, parts=parts,
        occurred_at=occurred, trust_level=TrustLevel.TRUSTED if owner else
            (TrustLevel.LOW if kind == "group" else TrustLevel.NORMAL),
        attention_hint=AttentionHint.IGNORE if own else AttentionHint.AMBIENT,
        directed_to_zhaoxi=directed, raw_ref=f"qq:{kind}:{conversation_id}:{message_id}",
        requeryable=True, metadata={"message_id": message_id, "reply_to": reply_to,
                                    "self_message": own, "sender_is_bot": sender_is_bot, "raw_message":event})
