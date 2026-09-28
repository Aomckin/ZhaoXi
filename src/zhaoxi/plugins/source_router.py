"""Route standard outbound messages back to the source that supplied an observation."""
import base64
import re
from zhaoxi.core.reply.parser import parse_reply
from zhaoxi.sdk.external_source import OutboundMessage, OutboundPart, ReplyTarget

def reply_target(observation):
    return ReplyTarget(source_plugin=observation.source_plugin or observation.source,
        conversation_id=observation.conversation_id or "",
        conversation_kind=observation.conversation_kind or "",
        message_ref=observation.metadata.get("message_id"),
        actor_ref=observation.actor_id,
        metadata={})

def outbound_message(content: str, emoji_service=None):
    parts = []
    for segment in parse_reply(content).segments:
        if segment.type == "text":
            parts.extend(OutboundPart(type="text", text=text.strip()) for text in
                         re.split(r"\n\s*\n+", segment.content) if text.strip())
        elif emoji_service is not None:
            match = emoji_service.resolve_tags(segment.requested_tags)
            if match and match.status == "matched" and match.emoji_id:
                path = emoji_service.image_path(match.emoji_id)
                if path and path.stat().st_size <= 10_485_760:
                    parts.append(OutboundPart(type="image",
                        data="base64://" + base64.b64encode(path.read_bytes()).decode("ascii")))
    return OutboundMessage(parts=parts)

class PerceptionSink:
    def __init__(self, perception, registry):
        self.perception, self.registry = perception, registry

    async def emit(self, observation):
        response = await self.perception.ingest(observation)
        if response:
            message = outbound_message(response, getattr(self.perception.agent, "emoji_service", None))
            result = await self.registry.send(reply_target(observation), message)
            if result.sent:
                await self.perception.reply_sent(observation, response, result.segment_count)
            else:
                self.perception.last_error = result.error
