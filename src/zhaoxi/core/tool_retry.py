"""One short-lived, scoped retry of an unexecuted Owner tool request."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import re
from time import monotonic

from zhaoxi.cognitive_stream.turn import current_turn

_LOCAL_SCOPE = ContextVar("tool_retry_scope", default=None)
RETRY_TTL_SECONDS = 300


@contextmanager
def local_retry_scope(channel: str, session_id: str):
    # Only the authenticated local gateway establishes this fallback identity.
    token = _LOCAL_SCOPE.set(("desktop", channel, session_id, "", "owner", ""))
    try:
        yield
    finally:
        _LOCAL_SCOPE.reset(token)


def current_retry_scope():
    turn = current_turn()
    if turn is None:
        return _LOCAL_SCOPE.get()
    event = turn.trigger_event
    if turn.audience != "owner" or event.actor_role != "OWNER" or not event.actor_id or not event.session_id:
        return None
    return (event.source, event.channel or turn.output_channel, event.session_id,
            event.conversation_id or "", event.actor_id, turn.reply_target or "")


def is_explicit_retry(text: str) -> bool:
    # Full matching prevents quoted/negated retries and added action scopes.
    # The final clause covers the observed retry without treating it as a new write.
    return bool(re.fullmatch(
        r"(?:你(?:现在)?|现在|请|麻烦(?:你)?|那(?:就)?|帮我|替我|可以|能不能|要不|嗯|好|[，,\s])*"
        r"(?:再试(?:一次|一下)?|重试(?:一次|一下)?|重新试(?:一次|一下)?)"
        r"(?:吧|呀|啊|呢|好吗|可以吗|行吗|[。.!！?？\s])*"
        r"(?:[，,]这个我(?:可)?不想自己(?:写|弄|做|处理)[。.!！\s]*)?", text.strip()))


@dataclass(frozen=True, slots=True)
class ToolRetryContext:
    request_id: str
    scope: tuple[str, ...]
    intent: str
    created_at: float

    @classmethod
    def capture(cls, request_id: str, intent: str):
        scope = current_retry_scope()
        # Do not silently truncate an operation's resource or action scope.
        if scope is None or not intent or len(intent) > 4000:
            return None
        return cls(request_id, scope, intent, monotonic())

    def matches(self, text: str) -> bool:
        return (current_retry_scope() == self.scope
                and 0 <= monotonic() - self.created_at <= RETRY_TTL_SECONDS
                and is_explicit_retry(text))
