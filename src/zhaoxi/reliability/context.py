"""Async-safe correlation identifiers for one request or background task."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from typing import Iterator


@dataclass(frozen=True, slots=True)
class CorrelationContext:
    trace_id: str
    request_id: str | None = None
    session_id: str | None = None
    goal_id: str | None = None
    workflow_run_id: str | None = None
    reflection_id: str | None = None
    invocation_id: str | None = None
    schedule_id: str | None = None

    def fields(self) -> dict[str, str]:
        return {key: value for key, value in asdict(self).items() if value is not None}


_current: ContextVar[CorrelationContext | None] = ContextVar(
    "zhaoxi_correlation_context", default=None
)


def current_correlation() -> CorrelationContext | None:
    return _current.get()


@contextmanager
def correlation_scope(context: CorrelationContext) -> Iterator[CorrelationContext]:
    token = _current.set(context)
    try:
        yield context
    finally:
        _current.reset(token)
