"""Bounded cross-channel retrieval with provenance-preserving output."""
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from .models import CognitiveEvent, CognitiveEventType
from .store import ExperienceStream

@dataclass(slots=True)
class AttentionContext:
    events: list[CognitiveEvent]
    session_id: str | None
    trigger_id: str | None

    def render(self, max_chars: int = 2400) -> str:
        # Reserve space for the newest evidence before adding older context.
        # Slicing a chronological string from the front used to discard the
        # exact Desktop reply a QQ user had just asked about.
        lines, used = [], 0
        for event in reversed(self.events):
            if not event.content:
                continue
            label = "Owner" if event.actor_role == "OWNER" else ("第三方发言" if event.actor_role not in {"SELF", "OWNER"} else "朝汐")
            prefix = f"[{event.occurred_at.isoformat()} {label}] "
            remaining = max_chars - used - len(prefix) - 1
            if remaining <= 0:
                break
            content = event.content[:min(500, remaining)]
            lines.append(prefix + content)
            used += len(prefix) + len(content) + 1
        return "\n".join(reversed(lines))

class AttentionRetriever:
    def __init__(self, stream: ExperienceStream):
        self.stream = stream
        self.last_result: list[str] = []
        self.last_cross_channel_result: list[str] = []

    def retrieve(self, query: str, *, session_id: str | None = None,
                 trigger_id: str | None = None, include_private: bool = True,
                 limit: int = 10, max_chars: int = 2400, horizon_days: int = 30,
                 older_than: datetime | None = None) -> AttentionContext:
        candidates = self.stream.query_since(datetime.now(UTC) - timedelta(days=horizon_days), limit=200)
        terms = set(re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9_.]{3,}", query.lower()))
        scored = []
        for index, event in enumerate(candidates):
            if event.event_id == trigger_id or not event.content or (older_than and event.occurred_at >= older_than):
                continue
            if not include_private and event.privacy_level in {"PRIVATE", "OWNER_PRIVATE"}:
                continue
            if session_id and session_id.startswith("qq/") and event.privacy_level in {"PRIVATE", "OWNER_PRIVATE"}:
                # QQ can recall what Owner said on Desktop, but not private tool,
                # workflow, decision or system data from the local machine.
                if event.event_type not in {CognitiveEventType.USER_MESSAGE,
                                            CognitiveEventType.EXTERNAL_MESSAGE,
                                            CognitiveEventType.ASSISTANT_REPLY}:
                    continue
            if event.event_type == CognitiveEventType.SOCIAL_SNAPSHOT and not re.search(
                    r"群|摘要|群聊", query):
                continue
            overlap = sum(term in event.content.lower() for term in terms)
            score = event.importance + event.attention_score + overlap * 2
            score += max(0, 1 - index / 50)
            if event.actor_role == "OWNER":
                score += 0.3
            scored.append((score, event))
        # Selection is based on relevance and time, never on channel quotas.
        selected, chars = [], 0
        for _, event in sorted(scored, key=lambda pair: pair[0], reverse=True):
            if chars + len(event.content or "") > max_chars:
                continue
            selected.append(event)
            chars += len(event.content or "")
            if len(selected) >= limit:
                break
        selected.sort(key=lambda event: (event.occurred_at, event.received_at, event.event_id))
        self.last_result = [event.event_id for event in selected]
        self.last_cross_channel_result = [event.event_id for event in selected
            if event.session_id != session_id]
        return AttentionContext(selected, session_id, trigger_id)
