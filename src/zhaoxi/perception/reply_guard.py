"""Deterministic boundary against non-owner bot reply loops."""
import re
from datetime import UTC, datetime, timedelta

from zhaoxi.perception.context import session_key

# Limit repeat exchanges with one actor and rapid handoffs between bots. Owner turns are exempt.
EXTERNAL_ACTOR_COOLDOWN = timedelta(minutes=5)
EXTERNAL_SESSION_COOLDOWN = timedelta(seconds=45)
BOT_REPLY_LOOKBACK = timedelta(hours=24)
_REQUEST = re.compile(r"[?？]|请|帮我|能否|能不能|可以|怎么|什么|为什么|为何|是否|要不要|回答|解释|告诉|怎么样|看图|看看图")
_MENTION = re.compile(r"@(?:\d+|朝汐)\s*")


def non_owner_reply_block_reason(item, stream=None, *, now: datetime | None = None,
                                 known_bot_ids: set[str] | None = None) -> str | None:
    """Return a reason to suppress a non-owner reply; observations remain recorded."""
    if item.actor_role == "OWNER":
        return None
    if item.conversation_kind != "private" and not item.directed_to_zhaoxi:
        return "not_directed"
    text = _MENTION.sub("", item.content or "").strip()
    has_image = any(part.type == "image" for part in item.effective_parts)
    if not has_image and (not text or not _REQUEST.search(text)):
        return "no_explicit_request"
    if stream is None:
        return None
    now = now or datetime.now(UTC)
    session_id = session_key(item)
    is_bot = bool(item.metadata.get("sender_is_bot") or
                  item.actor_id in (known_bot_ids or set()))
    since = now - (BOT_REPLY_LOOKBACK if is_bot else EXTERNAL_ACTOR_COOLDOWN)
    for reply in stream.recent_replies_in_session(session_id, since):
        # Replies from before this guard was installed have no explicit metadata.
        parent = stream.get(reply.reply_to_event_id) if reply.reply_to_event_id else None
        external = reply.metadata.get("external_reply") or (
            parent is not None and parent.actor_role != "OWNER")
        if not external:
            continue
        actor_id = reply.metadata.get("external_actor_id") or (parent.actor_id if parent else None)
        if actor_id and actor_id == item.actor_id:
            if not is_bot:
                return "recent_external_reply"
            owner_intervened = any(
                event.actor_role == "OWNER" and event.received_at > reply.received_at
                and event.event_type.value in {"USER_MESSAGE", "EXTERNAL_MESSAGE"}
                for event in stream.query_by_session(session_id, 200))
            if not owner_intervened:
                return "bot_already_answered"
        if reply.received_at >= now - EXTERNAL_SESSION_COOLDOWN:
            return "recent_external_reply"
    return None
