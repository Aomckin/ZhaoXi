"""Request-local, safe agent events and final action accounting."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Callable, Iterator

from zhaoxi.reliability import current_correlation


logger = logging.getLogger("OBSERVABILITY")

TOOL_LABELS = {
    "agenda_add": "添加日程", "agenda_update": "修改日程", "agenda_complete": "完成日程",
    "agenda_cancel": "取消日程", "agenda_list": "查询日程", "agenda_snapshot": "读取日程摘要",
    "add_job": "新增求职记录", "update_job": "修改求职记录", "update_stage": "更新求职进度",
    "add_follow_up": "添加求职跟进", "get_job": "查询求职记录", "search_jobs": "搜索求职记录",
    "get_summary": "查看求职摘要", "notes_add": "添加工作便签",
    "notes_update": "更新工作便签", "notes_resolve": "完成工作便签",
    "notes_delete": "删除工作便签", "notes_list": "查询工作便签", "notes_snapshot": "读取工作摘要",
    "search_memories": "检索记忆", "remember_memory": "保存记忆", "update_memory": "更新记忆",
    "forget_memory": "遗忘记忆", "archive_memory": "归档记忆", "save_emoji": "收藏表情",
    "current_time": "查询时间", "calculator": "计算", "archive_search": "检索书库",
    "archive_read": "阅读书库资料", "lifehud": "查看 Life HUD",
}


def tool_label(name: str) -> str:
    return TOOL_LABELS.get(name, name)


@dataclass(slots=True)
class AgentEvent:
    event_type: str
    trace_id: str
    request_id: str
    step_id: int | None
    stage: str
    outcome: str
    display_message: str
    tool_name: str | None = None
    tool_call_id: str | None = None
    invocation_id: str | None = None
    error_code: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def payload(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class ActionAttempt:
    tool_name: str
    tool_call_id: str
    invocation_id: str
    step_id: int | None
    status: str = "unknown"
    failure_kind: str | None = None
    superseded_by: str | None = None
    result_code: str | None = None
    record_id: str | None = None


@dataclass(slots=True)
class ActionTrace:
    trace_id: str
    request_id: str
    sink: Callable[[dict[str, object]], None] | None = None
    events: list[AgentEvent] = field(default_factory=list)
    actions: list[ActionAttempt] = field(default_factory=list)
    response_status: str = "pending"
    terminal_status: str | None = None
    current_step: int | None = None

    def emit(self, event_type: str, stage: str, outcome: str, display_message: str,
             *, step_id: int | None = None, tool_name: str | None = None,
             tool_call_id: str | None = None, invocation_id: str | None = None,
             error_code: str | None = None, metadata: dict[str, object] | None = None) -> AgentEvent:
        safe_metadata = dict(metadata or {})
        if stage == "task":
            safe_metadata.update(task_status=self.task_status, response_status=self.response_status)
        event = AgentEvent(event_type, self.trace_id, self.request_id, step_id, stage,
                           outcome, display_message, tool_name, tool_call_id,
                           invocation_id, error_code, safe_metadata)
        self.events.append(event)
        logger.info(
            "trace=%s request=%s step=%s stage=%s event=%s tool=%s tool_call_id=%s invocation_id=%s outcome=%s error_code=%s metadata=%s",
            event.trace_id, event.request_id, event.step_id, event.stage,
            event.event_type, event.tool_name, event.tool_call_id,
            event.invocation_id, event.outcome, event.error_code, event.metadata,
        )
        if self.sink is not None:
            self.sink({"type": "agent_event", "event": event.payload()})
        return event

    def start_tool(self, name: str, call_id: str, invocation_id: str, step: int | None) -> ActionAttempt:
        # A schema rejection cannot have changed external state. A later call to
        # the same tool is its repair; successful writes remain distinct actions.
        previous = self.actions[-1] if self.actions else None
        if (previous is not None and previous.tool_name == name and previous.status == "failed"
                and previous.failure_kind == "validation" and previous.step_id is not None
                and step is not None and step > previous.step_id):
            previous.status = "superseded"
            previous.superseded_by = invocation_id
            self.emit("tool_call_retrying", "tool_execution", "retrying",
                      f"正在修正{tool_label(name)}参数…", step_id=step, tool_name=name,
                      tool_call_id=call_id, invocation_id=invocation_id,
                      metadata={"supersedes_invocation_id": previous.invocation_id})
        attempt = ActionAttempt(name, call_id, invocation_id, step)
        self.actions.append(attempt)
        self.emit("tool_call_started", "tool_execution", "running", f"正在{tool_label(name)}…",
                  step_id=step, tool_name=name, tool_call_id=call_id,
                  invocation_id=invocation_id)
        return attempt

    def finish_tool(self, attempt: ActionAttempt, *, success: bool,
                    failure_kind: str | None = None, unknown: bool = False,
                    result_code: str | None = None, record_id: str | None = None,
                    metadata: dict[str, object] | None = None) -> None:
        attempt.status = "completed" if success else "unknown" if unknown else "failed"
        attempt.failure_kind = failure_kind
        attempt.result_code = result_code
        attempt.record_id = record_id
        event_type = ("tool_call_succeeded" if success else
                      "tool_validation_failed" if failure_kind == "validation" else "tool_call_failed")
        self.emit(event_type, "tool_execution", "success" if success else "warning" if unknown else "failed",
                  f"已{tool_label(attempt.tool_name)}" if success else
                  f"{tool_label(attempt.tool_name)}参数校验失败，正在修正…" if failure_kind == "validation" else
                  f"{tool_label(attempt.tool_name)}结果未知" if unknown else f"{tool_label(attempt.tool_name)}失败",
                  step_id=attempt.step_id, tool_name=attempt.tool_name,
                  tool_call_id=attempt.tool_call_id, invocation_id=attempt.invocation_id,
                  error_code=None if success else "tool_validation_error" if failure_kind == "validation" else "tool_execution_error",
                  metadata={**(metadata or {}), **({"result_code": result_code} if result_code else {}),
                            **({"record_id": record_id} if record_id else {})})

    @property
    def task_status(self) -> str:
        if self.terminal_status is not None:
            return self.terminal_status
        statuses = {action.status for action in self.actions if action.status != "superseded"}
        if "failed" in statuses or "unknown" in statuses:
            return "partial" if "completed" in statuses else "failed"
        return "completed"

    @property
    def task_outcome(self) -> str:
        return {"completed": "success", "partial": "warning", "failed": "failed",
                "waiting_for_permission": "info"}.get(self.task_status, "info")

    def summary(self) -> dict[str, object]:
        return {"trace_id": self.trace_id, "request_id": self.request_id,
                "task_status": self.task_status, "response_status": self.response_status,
                "actions": [asdict(item) for item in self.actions]}


_current: ContextVar[ActionTrace | None] = ContextVar("zhaoxi_action_trace", default=None)


def current_trace() -> ActionTrace | None:
    return _current.get()


@contextmanager
def action_trace_scope(sink: Callable[[dict[str, object]], None] | None = None) -> Iterator[ActionTrace]:
    correlation = current_correlation()
    if correlation is None:
        raise RuntimeError("Action trace requires correlation context")
    trace = ActionTrace(correlation.trace_id, correlation.request_id or correlation.trace_id, sink)
    token = _current.set(trace)
    try:
        yield trace
    finally:
        _current.reset(token)
