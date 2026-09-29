"""Bounded structured execution traces."""

from collections import defaultdict, deque
from typing import Any
from uuid import uuid4

from zhaoxi.planner.models import Goal, TraceEvent
from zhaoxi.observability import current_trace


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
        details = dict(metadata or {})
        if goal.current_plan:
            details["steps"] = [{"id": item.id, "description": item.description,
                                 "status": item.status.value} for item in goal.current_plan.steps]
            step = next((item for item in goal.current_plan.steps if item.id == step_id), None)
            if step:
                details["step_description"] = step.description
        event = TraceEvent(
            trace_id=self.trace_id_for(goal.id),
            goal_id=goal.id,
            plan_revision=goal.current_plan.revision if goal.current_plan else None,
            step_id=step_id,
            event_type=event_type,
            metadata=details,
        )
        self._events[goal.id].append(event)
        PlannerActionTraceAdapter.forward(event)
        return event

    def events(self, goal_id: str) -> list[TraceEvent]:
        return list(self._events.get(goal_id, ()))


class PlannerActionTraceAdapter:
    """Bridge planner lifecycle events to the request-local ActionTrace."""

    EVENT_MAP = {
        "goal_created": "planner_started",
        "plan_created": "planner_plan_created",
        "step_started": "planner_step_started",
        "step_completed": "planner_step_completed",
        "plan_revised": "planner_replanned",
        "task_completed": "planner_finished",
        "task_failed": "planner_failed",
        "task_cancelled": "planner_cancelled",
        "step_retried": "planner_step_retrying",
        "permission_requested": "planner_waiting_permission",
        "input_requested": "planner_waiting_input",
    }

    @classmethod
    def forward(cls, event: TraceEvent) -> None:
        trace = current_trace()
        mapped = cls.EVENT_MAP.get(event.event_type)
        if trace is None or mapped is None:
            return
        labels = {"planner_started": "正在制定计划", "planner_plan_created": "已生成行动计划",
                  "planner_step_started": "正在执行计划步骤", "planner_step_completed": "计划步骤已完成",
                  "planner_replanned": "已调整行动计划", "planner_finished": "计划已完成",
                  "planner_failed": "计划未完成", "planner_cancelled": "计划已取消",
                  "planner_step_retrying": "正在重试计划步骤", "planner_waiting_permission": "计划正在等待确认",
                  "planner_waiting_input": "计划正在等待补充信息"}
        description = event.metadata.get("step_description")
        message = labels[mapped] + (f"：{description}" if description else "")
        outcome = "failed" if mapped == "planner_failed" else "success" if mapped.endswith(("completed", "finished")) else "running"
        trace.emit(mapped, "planner", outcome, message, step_id=event.step_id, metadata={
                       "goal_id": event.goal_id, "planner_step_id": event.step_id,
                       "plan_revision": event.plan_revision, **event.metadata})
