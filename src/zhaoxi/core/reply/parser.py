"""Parser for the deliberately small v1 reply DSL."""

import re

from zhaoxi.core.reply.segments import EmojiSegment, ReplySequence, TextSegment


EMOJI_DSL = re.compile(r"\[emoji:([^\]]*)\]", re.IGNORECASE)


def _tags(value: str) -> list[str]:
    values = []
    for item in re.split(r"[,，]", value):
        tag = item.strip()
        if tag and tag not in values:
            values.append(tag)
    return values[:3]


def parse_reply(raw_reply: str | None) -> ReplySequence:
    """Parse valid emoji markers while leaving malformed markers as ordinary text."""
    raw = raw_reply or ""
    segments: list[TextSegment | EmojiSegment] = []
    def append_text(value: str) -> None:
        text = value.strip()
        if not text:
            return
        if segments and isinstance(segments[-1], TextSegment):
            segments[-1].content += text
        else:
            segments.append(TextSegment(content=text))

    cursor = 0
    for match in EMOJI_DSL.finditer(raw):
        append_text(raw[cursor:match.start()])
        tags = _tags(match.group(1))
        if tags:
            segments.append(EmojiSegment(requested_tags=tags))
        cursor = match.end()
    append_text(raw[cursor:])
    return ReplySequence(segments=segments, raw_reply=raw)
