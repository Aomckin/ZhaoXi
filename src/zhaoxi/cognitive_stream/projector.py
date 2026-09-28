"""Local conversation projections over the global event stream."""
from dataclasses import dataclass, field
from typing import Any
from .models import CognitiveEvent
from .store import ExperienceStream

@dataclass(slots=True)
class SessionView:
    session_id: str
    recent_events: list[CognitiveEvent]
    reply_target: str | None = None
    channel_metadata: dict[str, Any] = field(default_factory=dict)

class SessionProjector:
    def __init__(self, stream: ExperienceStream):
        self.stream = stream

    def project(self, session_id: str, *, limit: int = 12,
                reply_target: str | None = None) -> SessionView:
        events = list(reversed(self.stream.query_by_session(session_id, limit)))
        latest = events[-1] if events else None
        return SessionView(session_id, events, reply_target,
                           {"channel": latest.channel if latest else None,
                            "conversation_id": latest.conversation_id if latest else None})
