"""Route standard outbound messages back to the source that supplied an observation."""
import base64
import re
from zhaoxi.core.reply import ReplySequence, ResolvedReply, parse_reply
from zhaoxi.sdk.external_source import OutboundMessage, OutboundPart, ReplyTarget

def reply_target(observation):
    return ReplyTarget(source_plugin=observation.source_plugin or observation.source,
        conversation_id=observation.conversation_id or "",
        conversation_kind=observation.conversation_kind or "",
        message_ref=observation.metadata.get("message_id"),
        actor_ref=observation.actor_id,
        metadata={})

def _prepare_outbound(content: str, emoji_service=None):
    resolved = isinstance(content, ResolvedReply)
    sequence = content.reply_sequence if resolved else parse_reply(content)
    parts, delivered = [], []
    for segment in sequence.segments:
        if segment.type == "text":
            text_parts = [OutboundPart(type="text", text=text.strip()) for text in
                          re.split(r"\n\s*\n+", segment.content) if text.strip()]
            parts.extend(text_parts)
            if text_parts:
                delivered.append(segment)
        elif emoji_service is not None and getattr(emoji_service, "enabled", True):
            emoji_id = segment.emoji_id
            if not resolved:
                match = emoji_service.resolve_tags(segment.requested_tags)
                emoji_id = match.emoji_id if match and match.status == "matched" else None
            if not emoji_id:
                continue
            path = emoji_service.image_path(emoji_id)
            try:
                if path and path.stat().st_size <= 10_485_760:
                    parts.append(OutboundPart(type="image",
                        data="base64://" + base64.b64encode(path.read_bytes()).decode("ascii")))
                    delivered.append(segment)
            except OSError:
                # A removed or unreadable asset must not prevent remaining text.
                continue
    acknowledged = ResolvedReply(ReplySequence(segments=delivered)) if resolved else content
    return OutboundMessage(parts=parts), acknowledged


def outbound_message(content: str, emoji_service=None):
    return _prepare_outbound(content, emoji_service)[0]


class PerceptionSink:
    def __init__(self, perception, registry):
        self.perception, self.registry = perception, registry

    async def emit(self, observation):
        response = await self.perception.ingest(observation)
        if response:
            message, acknowledged = _prepare_outbound(
                response, getattr(self.perception.agent, "emoji_service", None))
            if not message.parts:
                self.perception.last_error = "outbound_reply_empty"
                return
            result = await self.registry.send(reply_target(observation), message)
            if result.sent:
                await self.perception.reply_sent(observation, acknowledged, result.segment_count)
            else:
                self.perception.last_error = result.error
