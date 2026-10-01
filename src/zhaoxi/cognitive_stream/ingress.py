"""Normalize ingress from desktop, perception and actions."""
from datetime import UTC, datetime
from .models import CognitiveEvent, CognitiveEventType, EventPart
from .store import ExperienceStream
from .turn import current_turn

class CognitiveIngress:
    def __init__(self, stream: ExperienceStream):
        self.stream = stream
        self.errors = 0

    def _append(self, event: CognitiveEvent) -> CognitiveEvent:
        try:
            return self.stream.append(event)
        except Exception:
            self.errors += 1
            raise

    def desktop(self, content: str, *, message_id: str | None = None,
                images: list[str] | None = None, session_id: str = "local",
                channel: str = "desktop", occurred_at: datetime | None = None) -> CognitiveEvent:
        return self._append(CognitiveEvent(
            event_type=CognitiveEventType.USER_MESSAGE, source="desktop", channel=channel,
            turn_id=message_id,
            session_id=session_id, actor_id="owner", actor_role="OWNER", content=content,
            occurred_at=occurred_at or datetime.now(UTC),
            parts=[EventPart(type="image", url=image) for image in (images or [])], trust_level="TRUSTED",
            source_refs=["desktop:" + message_id] if message_id else [], importance=0.7))

    def observation(self, item, *, session_id: str | None = None,
                    images: list[str] | None = None) -> CognitiveEvent:
        refs = item.metadata.get("merged_refs") or ([item.raw_ref] if item.raw_ref else ["observation:" + item.observation_id])
        parts = [EventPart.model_validate(part.model_dump()) for part in item.effective_parts]
        existing_images = {part.url for part in parts if part.type == "image"}
        parts.extend(EventPart(type="image", url=image) for image in (images or []) if image not in existing_images)
        return self._append(CognitiveEvent(
            event_type=CognitiveEventType.EXTERNAL_MESSAGE, source=item.source, channel=item.source,
            turn_id=item.observation_id,
            session_id=session_id, conversation_id=item.conversation_id,
            actor_id=item.actor_id, actor_name=item.actor_name, actor_role=item.actor_role,
            content=item.content, parts=parts, trust_level=str(item.trust_level),
            privacy_level="OWNER_PRIVATE" if item.actor_role == "OWNER" and item.conversation_kind == "private" else "SOCIAL",
            occurred_at=item.occurred_at, received_at=item.received_at,
            source_refs=refs, importance=0.7 if item.actor_role == "OWNER" else 0.3,
            metadata={**{key:item.metadata[key] for key in ("raw_message","raw_observations") if key in item.metadata},
                      "conversation_kind": item.conversation_kind, "source_kind": item.source_kind,
                      "source_plugin": item.source_plugin,
                      "directed_to_zhaoxi": item.directed_to_zhaoxi,
                      "sender_is_bot": bool(item.metadata.get("sender_is_bot"))}))

    def record(self, event_type: CognitiveEventType, content: str, *, source: str,
               channel: str | None = None, session_id: str | None = None,
               parent_refs: list[str] | None = None, source_refs: list[str] | None = None,
               metadata: dict | None = None, privacy_level: str = "PRIVATE",
               turn_id: str | None = None, reply_to_event_id: str | None = None,
               caused_by_event_id: str | None = None) -> CognitiveEvent:
        turn = current_turn()
        parent = (parent_refs or [turn.trigger_event.event_id] if turn else parent_refs or [])
        trigger_id = turn.trigger_event.event_id if turn else (parent[0] if parent else None)
        trigger = turn.trigger_event if turn else (self.stream.get(trigger_id) if trigger_id else None)
        source_metadata = {key:trigger.metadata[key] for key in ("conversation_kind", "source_plugin") if key in trigger.metadata} if trigger else {}
        return self._append(CognitiveEvent(
            event_type=event_type, source=source, channel=channel, session_id=session_id,
            conversation_id=trigger.conversation_id if trigger else (metadata or {}).get("conversation_id"),
            turn_id=turn_id or (turn.turn_id if turn else None),
            reply_to_event_id=reply_to_event_id or (trigger_id if event_type == CognitiveEventType.ASSISTANT_REPLY else None),
            caused_by_event_id=caused_by_event_id or (trigger_id if event_type != CognitiveEventType.ASSISTANT_REPLY else None),
            actor_role="SELF", trust_level="TRUSTED", privacy_level=privacy_level,
            content=content, parent_refs=parent, source_refs=source_refs or [],
            metadata={**source_metadata, **(metadata or {})}))
