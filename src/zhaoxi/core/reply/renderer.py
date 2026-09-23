"""Resolve a ReplySequence and commit it to the conversation in order."""

import logging
import re
from uuid import uuid4

from zhaoxi.core.conversation import Conversation
from zhaoxi.core.reply.parser import parse_reply
from zhaoxi.core.reply.segments import EmojiSegment, ReplySequence, TextSegment

logger = logging.getLogger("REPLY")


_CATALOG_LABEL = re.compile(r"\[([^\[\]\r\n:]{1,120})\]")


def _normalize_catalog_labels(raw: str, emoji_service) -> str:
    """Accept a copied full catalog label only when it names an enabled emoji."""
    if emoji_service is None or not emoji_service.enabled:
        return raw
    labels = {
        tuple(tag.strip().casefold() for tag in entry.tags)
        for entry in emoji_service.entries if entry.enabled and len(entry.tags) >= 2
    }

    def replace(match: re.Match[str]) -> str:
        tags = [tag.strip() for tag in re.split(r"[,，]", match.group(1))]
        if tuple(tag.casefold() for tag in tags) not in labels:
            return match.group(0)
        return "[emoji:" + ",".join(tags[-3:]) + "]"

    return _CATALOG_LABEL.sub(replace, raw)


def catalog_emoji_prefix(raw: str, emoji_service) -> tuple[str, str] | None:
    """Identify a legacy copied catalog label at the start of a saved reply."""
    if emoji_service is None or not emoji_service.enabled:
        return None
    match = _CATALOG_LABEL.match(raw)
    if match is None:
        return None
    tags = tuple(tag.strip().casefold() for tag in re.split(r"[,，]", match.group(1)))
    entry = next((item for item in emoji_service.entries
                  if item.enabled and len(item.tags) >= 2
                  and tuple(tag.strip().casefold() for tag in item.tags) == tags), None)
    return (entry.id, raw[match.end():].lstrip()) if entry is not None else None


def commit_reply(conversation: Conversation, raw_reply: str | None, emoji_service=None) -> tuple[ReplySequence, list[str]]:
    parsed = parse_reply(_normalize_catalog_labels(raw_reply or "", emoji_service))
    parsed.raw_reply = raw_reply or ""
    resolved: list[TextSegment | EmojiSegment] = []
    no_match: list[list[str]] = []
    for segment in parsed.segments:
        if isinstance(segment, TextSegment):
            resolved.append(segment)
            continue
        result = emoji_service.resolve_tags(segment.requested_tags) if emoji_service is not None else None
        if result is None or result.status != "matched" or not result.emoji_id:
            no_match.append(segment.requested_tags)
            logger.info("emoji_resolve_no_match requested_tags=%s", segment.requested_tags)
            continue
        resolved.append(segment.model_copy(update={
            "emoji_id": result.emoji_id,
            "image_url": f"/api/expression/emoji/{result.emoji_id}",
        }))

    sequence = ReplySequence(segments=resolved, raw_reply=parsed.raw_reply)
    group_id = uuid4().hex
    message_ids: list[str] = []
    first = True
    for segment in sequence.segments:
        common = {
            "reply_group_id": group_id,
            "raw_reply": sequence.raw_reply if first else None,
        }
        if isinstance(segment, TextSegment):
            message = conversation.add_assistant(
                segment.content,
                source="reply_dsl" if any(isinstance(item, EmojiSegment) for item in parsed.segments) else None,
                segment_type="text",
                **common,
            )
        else:
            message = conversation.add_assistant_image(
                segment.image_url or "",
                source="emoji",
                emoji_id=segment.emoji_id,
                requested_tags=segment.requested_tags,
                segment_type="emoji",
                **common,
            )
        first = False
        message_ids.append(message.message_id)
    if not sequence.segments:
        message = conversation.add_assistant("", raw_reply=sequence.raw_reply, reply_group_id=group_id)
        message_ids.append(message.message_id)
    return sequence, message_ids
