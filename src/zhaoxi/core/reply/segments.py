"""Structured segments produced from one model reply."""

from typing import Literal

from pydantic import BaseModel, Field


class TextSegment(BaseModel):
    type: Literal["text"] = "text"
    content: str


class EmojiSegment(BaseModel):
    type: Literal["emoji"] = "emoji"
    requested_tags: list[str] = Field(default_factory=list, max_length=3)
    emoji_id: str | None = None
    image_url: str | None = None


class ReplySequence(BaseModel):
    segments: list[TextSegment | EmojiSegment] = Field(default_factory=list)
    raw_reply: str = ""

    @property
    def visible_text(self) -> str:
        return "\n\n".join(
            segment.content for segment in self.segments
            if isinstance(segment, TextSegment) and segment.content
        )


class ResolvedReply(str):
    """Channel text with its resolved segments, carried with this reply only."""

    reply_sequence: ReplySequence

    def __new__(cls, sequence: ReplySequence):
        reply = super().__new__(cls, sequence.visible_text)
        reply.reply_sequence = sequence
        return reply

    def __bool__(self) -> bool:
        return bool(self.reply_sequence.segments)

    @property
    def history_text(self) -> str:
        return "\n\n".join(
            segment.content if isinstance(segment, TextSegment) else
            "[曾使用表情：" + "、".join(segment.requested_tags) + "]"
            for segment in self.reply_sequence.segments
        )
