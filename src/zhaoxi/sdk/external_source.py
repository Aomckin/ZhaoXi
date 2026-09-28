"""Public external source protocol."""
from typing import Any, Protocol
from pydantic import BaseModel, Field
from zhaoxi.perception.models import Observation

class SourceCapabilities(BaseModel):
    text_in: bool = False
    text_out: bool = False
    image_in: bool = False
    image_out: bool = False
    audio_in: bool = False
    audio_out: bool = False
    file_in: bool = False
    file_out: bool = False
    reply: bool = False
    mention: bool = False
    private_chat: bool = False
    group_chat: bool = False
    realtime: bool = False

class ReplyTarget(BaseModel):
    source_plugin: str
    conversation_id: str
    conversation_kind: str
    message_ref: str | None = None
    actor_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class OutboundPart(BaseModel):
    type: str
    text: str | None = None
    data: str | None = None

class OutboundMessage(BaseModel):
    parts: list[OutboundPart]
    reply_to: str | None = None
    expression_policy: str | None = None

class SendResult(BaseModel):
    sent: bool
    segment_count: int = 0
    error: str | None = None

class ObservationSink(Protocol):
    async def emit(self, observation: Observation) -> None: ...

class ExternalSourcePlugin(Protocol):
    plugin_id: str
    async def start(self, sink: ObservationSink) -> None: ...
    async def stop(self) -> None: ...
    def capabilities(self) -> SourceCapabilities: ...
    def diagnostics(self) -> dict[str, Any]: ...

class InteractiveSourcePlugin(ExternalSourcePlugin, Protocol):
    async def send(self, target: ReplyTarget, content: OutboundMessage) -> SendResult: ...
    async def reply(self, target: ReplyTarget, reply_to: str, content: OutboundMessage) -> SendResult: ...
