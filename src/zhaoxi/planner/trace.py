"""Bounded structured execution traces."""

from collections import defaultdict, deque
from typing import Any
from uuid import uuid4

from zhaoxi.planner.models import Goal, TraceEvent


class TraceRecorder:
    def __init__(self, max_events: int = 200) -> None:
        self.max_events = max_events
        self._events: dict[str, deque[TraceEvent]] = defaultdict(
            lambda: deque(maxlen=self.max_events)
        )
        self._trace_ids: dict[str, str] = {}

    def trace_id_for(self, goal_id: str) -> str:
        return self._trace_ids.setdefault(goal_id, uuid4().hex)

    def record(
        self,
        goal: Goal,
        event_type: str,
        *,
        step_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TraceEvent:
        event = TraceEvent(
            trace_id=self.trace_id_for(goal.id),
            goal_id=goal.id,
            plan_revision=goal.current_plan.revision if goal.current_plan else None,
            step_id=step_id,
            event_type=event_type,
            metadata=metadata or {},
        )
        self._events[goal.id].append(event)
        return event

    def events(self, goal_id: str) -> list[TraceEvent]:
        return list(self._events.get(goal_id, ()))
