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
