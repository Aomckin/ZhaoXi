"""Request-local cognitive anchor for one model turn."""
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from uuid import uuid4
from threading import Lock

from .models import CognitiveEvent


@dataclass(frozen=True)
class CognitiveTurnContext:
    trigger_event: CognitiveEvent
    request_id: str = field(default_factory=lambda: uuid4().hex)
    output_channel: str = "desktop"
    audience: str = "owner"
    expression_policy: str = ""
    reply_target: str | None = None
    images: tuple[str, ...] = ()

    @property
    def turn_id(self) -> str:
        return self.trigger_event.turn_id or self.trigger_event.event_id


_ACTIVE_LOCK = Lock()
_ACTIVE_TURNS: dict[str, CognitiveTurnContext] = {}

_CURRENT_TURN: ContextVar[CognitiveTurnContext | None] = ContextVar("cognitive_turn", default=None)


def current_turn() -> CognitiveTurnContext | None:
    turn = _CURRENT_TURN.get()
    if turn is None:
        return None
    with _ACTIVE_LOCK:
        return turn if _ACTIVE_TURNS.get(turn.request_id) is turn else None


def set_current_turn(context: CognitiveTurnContext) -> Token:
    token = _CURRENT_TURN.set(context)
    with _ACTIVE_LOCK:
        _ACTIVE_TURNS[context.request_id] = context
    return token


def reset_current_turn(token: Token) -> None:
    context = _CURRENT_TURN.get()
    with _ACTIVE_LOCK:
        if context is not None:
            _ACTIVE_TURNS.pop(context.request_id, None)
    _CURRENT_TURN.reset(token)


def active_turns() -> list[dict]:
    with _ACTIVE_LOCK:
        return [{"request_id": turn.request_id, "turn_id": turn.turn_id,
                 "trigger_event_id": turn.trigger_event.event_id,
                 "output_channel": turn.output_channel, "audience": turn.audience,
                 "reply_target": turn.reply_target, "image_count": len(turn.images)}
                for turn in _ACTIVE_TURNS.values()]
