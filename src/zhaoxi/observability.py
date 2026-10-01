"""Request-local, safe agent events and final action accounting."""

from __future__ import annotations

import re
import logging
import time
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
    "get_summary": "查看求职摘要",
    "search_memories": "检索记忆", "remember_memory": "保存记忆", "update_memory": "更新记忆",
    "forget_memory": "遗忘记忆", "archive_memory": "归档记忆", "save_emoji": "收藏表情",
    "current_time": "查询时间", "calculator": "计算", "archive_search": "检索书库",
    "archive_read": "阅读书库资料", "lifehud": "查看 Life HUD",
}


def tool_label(name: str) -> str:
    return TOOL_LABELS.get(name, "执行操作")


@dataclass(slots=True)
class AgentEvent:
    event_type: str
    trace_id: str
    request_id: str
    step_id: int | str | None
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
    step_id: int | str | None
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
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    started_monotonic: float = field(default_factory=time.monotonic)
    finished_at: str | None = None
    stage_ms: dict[str, float] = field(default_factory=dict)
    _stage_starts: dict[str, float] = field(default_factory=dict)
    llm_calls: list[dict[str, object]] = field(default_factory=list)
    tool_calls: list[dict[str, object]] = field(default_factory=list)
    memory_hits: int = 0
    memory_candidates: list[dict[str, object]] = field(default_factory=list)
    planner_used: bool = False
    decision_used: bool = False
    first_reply_ms: float | None = None
    final_response_ms: float | None = None
    final_reply_ready_ms: float | None = None
    interim_replies: int = 0
    route: str | None = None
    runtime_lane: str | None = None
    route_source: str | None = None
    fast_gate_reason: str | None = None
    fast_gate_details: dict[str, object] = field(default_factory=dict)
    router_required: bool = False
    router_override: bool = False
    router_final_lane: str | None = None
    router_to_fast_count: int = 0
    fast_escalation_count: int = 0
    fast_escalation_kind: str | None = None
    escalation_reason: str | None = None
    extra_round_reason: str | None = None
    tool_rounds: int = 0
    catalog_inspections: int = 0
    interim_enabled: bool = True
    interim_threshold_seconds: float = 10
    interim_max_count: int = 1
    planner_interim_max_count: int = 2
    _last_interim_progress: str = ""
    planner_progress_version: int = 0
    _last_interim_progress_version: int = 0
    metrics_enabled: bool = True
    _tool_starts: dict[str, float] = field(default_factory=dict)
    _interval_starts: dict[str, float] = field(default_factory=dict)
    intervals: list[tuple[float, float]] = field(default_factory=list)

    def emit(self, event_type: str, stage: str, outcome: str, display_message: str,
             *, step_id: int | str | None = None, tool_name: str | None = None,
             tool_call_id: str | None = None, invocation_id: str | None = None,
             error_code: str | None = None, metadata: dict[str, object] | None = None) -> AgentEvent:
        safe_metadata = dict(metadata or {})
        if stage == "task":
            safe_metadata.update(task_status=self.task_status, response_status=self.response_status)
        event = AgentEvent(event_type, self.trace_id, self.request_id, step_id, stage,
                           outcome, display_message, tool_name, tool_call_id,
                           invocation_id, error_code, safe_metadata)
        self.events.append(event)
        self._observe(event)
        logger.info(
            "trace=%s request=%s step=%s stage=%s event=%s tool=%s tool_call_id=%s invocation_id=%s outcome=%s error_code=%s metadata=%s",
            event.trace_id, event.request_id, event.step_id, event.stage,
            event.event_type, event.tool_name, event.tool_call_id,
            event.invocation_id, event.outcome, event.error_code, event.metadata,
        )
        if self.sink is not None:
            self.sink({"type": "agent_event", "event": event.payload()})
        return event

    def _observe(self, event: AgentEvent) -> None:
        if event.event_type in {"planner_step_completed", "planner_replanned"}:
            self.planner_progress_version += 1
        if not self.metrics_enabled:
            return
        stage = event.stage
        now = time.monotonic()
        if stage not in {"runtime", "request", "task", "metrics"}:
            prefix = re.sub(r"_(started|finished|succeeded|failed|completed|cancelled)$", "", event.event_type)
            key = prefix + ":" + str(event.invocation_id or event.step_id or event.metadata.get("index") or "")
            if event.event_type.endswith("_started"):
                self._interval_starts[key] = now
            elif event.event_type.endswith(("_finished", "_succeeded", "_failed", "_completed", "_cancelled")):
                begin = self._interval_starts.pop(key, None)
                if begin is not None:
                    self.intervals.append((begin, now))
        if event.event_type in {"routing_started", "model_step_started", "memory_search_started", "response_generation_started",
                                "memory_maintenance_started", "auto_memory_started", "planner_started",
                                "decision_started", "workflow_started", "current_cognition_started"} and stage in {
                                "routing", "memory_search", "response_generation", "memory", "planner",
                                "decision", "workflow", "current_cognition"}:
            self._stage_starts.setdefault(stage, time.monotonic())
        if event.event_type in {"routing_finished", "model_step_finished", "model_step_failed", "memory_search_finished", "memory_search_failed",
                                "response_generation_succeeded", "response_generation_failed",
                                "memory_maintenance_finished", "memory_maintenance_failed",
                                "auto_memory_finished", "auto_memory_failed", "current_cognition_failed", "planner_finished", "planner_failed", "planner_cancelled", "decision_finished",
                                "workflow_finished", "current_cognition_finished"} and stage in self._stage_starts:
            elapsed = (time.monotonic() - self._stage_starts.pop(stage)) * 1000
            self.stage_ms[stage] = self.stage_ms.get(stage, 0) + elapsed
            event.metadata.setdefault("duration_ms", round(elapsed, 2))
        if event.event_type == "memory_search_finished":
            self.memory_hits += int(event.metadata.get("hit_count") or 0)
        if event.event_type == "tool_call_started" and event.invocation_id:
            self._tool_starts[event.invocation_id] = time.monotonic()
        if event.event_type in {"tool_call_succeeded", "tool_call_failed", "tool_validation_failed", "tool_call_waiting_permission"} and event.invocation_id:
            started = self._tool_starts.pop(event.invocation_id, None)
            self.tool_calls.append({"tool_name": event.tool_name, "step_id": event.step_id,
                                    "invocation_id": event.invocation_id,
                                    "duration_ms": round((time.monotonic() - started) * 1000, 2) if started else None,
                                    "success": event.outcome == "success", "retry_count": int(event.event_type == "tool_validation_failed"),
                                    "waiting_for_permission": event.event_type == "tool_call_waiting_permission"})
        if event.event_type in {"tool_call_succeeded", "tool_call_failed", "tool_validation_failed", "tool_call_waiting_permission"} and self.tool_calls:
            event.metadata.setdefault("duration_ms", self.tool_calls[-1]["duration_ms"])
        if stage == "planner":
            key = f"planner_step:{event.step_id}"
            if event.event_type == "planner_step_started":
                self._stage_starts[key] = time.monotonic()
            elif event.event_type in {"planner_step_completed", "planner_step_retrying"}:
                started = self._stage_starts.pop(key, None)
                if started is not None:
                    event.metadata["duration_ms"] = round((time.monotonic() - started) * 1000, 2)
            self.planner_used = True
        if stage == "decision":
            self.decision_used = True

    def record_memory_candidates(self, results) -> None:
        """Keep a bounded local-debug snapshot of the candidates actually used."""
        candidates = []
        for rank, item in enumerate(list(results)[:20], start=1):
            record = item.record
            content = str(record.content or "")
            candidates.append({
                "rank": rank,
                "id": record.id,
                "content": content[:500] + ("…" if len(content) > 500 else ""),
                "kind": getattr(record.kind, "value", str(record.kind)),
                "status": getattr(record.status, "value", str(record.status)),
                "cluster": getattr(getattr(item, "cluster", None), "topic", None),
                "final_score": item.score,
                "contextual_relevance": item.contextual_relevance,
                "text_score": item.text_score,
                "semantic_score": item.semantic_score,
                "graph_score": item.graph_score,
                "time_score": item.time_score,
                "activation_score": item.activation_score,
                "importance_score": item.importance_score,
                "why_selected": list(item.why_selected),
                "candidate_source":list(getattr(item,"candidate_source",[])),
                "retrieval_mode":str(getattr(item,"retrieval_mode","ASSOCIATIVE")),
                "cluster_score":getattr(item,"cluster_score",0),"cluster_rank":getattr(item,"cluster_rank",None),
            })
        self.memory_candidates = candidates

    def record_interval(self, stage: str, started: float) -> None:
        if not self.metrics_enabled:
            return
        ended = time.monotonic()
        self.intervals.append((started, ended))
        duration = (ended - started) * 1000
        self.stage_ms[stage] = self.stage_ms.get(stage, 0) + duration
        self.emit(stage + "_finished", stage, "success", "阶段处理已结束",
                  metadata={"duration_ms": round(duration, 2)})

    def emit_interim(self, content: str, *, reason: str = "agent", progress: str = "") -> bool:
        content = content.strip()
        limit = self.planner_interim_max_count if self.planner_used else self.interim_max_count
        if not self.interim_enabled or self.sink is None or self.finished_at is not None or self.interim_replies >= limit:
            return False
        if time.monotonic() - self.started_monotonic < self.interim_threshold_seconds:
            return False
        if reason == "agent" and not self.actions and (self.current_step or 0) < 2:
            return False
        if not content or len(content) > 180 or any(term in content.lower() for term in (
                "goal_id", "trace_id", "invocation_id", "token", "llm #", "step_id")):
            return False
        if any(term in content for term in ("已经完成", "问题解决", "我查到了", "已经更新")):
            return False
        if self.interim_replies and (not progress.strip() or progress.strip() == self._last_interim_progress
                                     or self.planner_progress_version <= self._last_interim_progress_version):
            return False
        self.interim_replies += 1
        self._last_interim_progress = progress.strip()
        self._last_interim_progress_version = self.planner_progress_version
        self.first_reply()
        event = self.emit("interim_response_emitted", "interim_response", "info", "朝汐已先回应，任务仍在继续",
                          metadata={"sequence": self.interim_replies, "reason": reason})
        if self.sink:
            self.sink({"type": "interim_reply", "request_id": self.request_id,
                       "trace_id": self.trace_id, "sequence": self.interim_replies,
                       "content": content, "emitted_at": event.timestamp,
                       "visible_to_user": True, "terminates_turn": False})
        return True

    def first_reply(self) -> None:
        if self.first_reply_ms is None:
            self.first_reply_ms = round((time.monotonic() - self.started_monotonic) * 1000, 2)

    def finish(self) -> None:
        if self.finished_at is not None:
            return
        self.finished_at = datetime.now(UTC).isoformat()
        self.final_response_ms = round((time.monotonic() - self.started_monotonic) * 1000, 2)
        self.first_reply()
        public_metrics = {
            key: value for key, value in self.metrics().items()
            if key not in {"timeline", "memory_candidates"}
        }
        self.emit("runtime_metrics_finalized", "metrics", "success", "运行指标已汇总",
                  metadata={"runtime_metrics": public_metrics})

    def metrics(self) -> dict[str, object]:
        if not self.metrics_enabled:
            return {"enabled": False, "request_id": self.request_id, "trace_id": self.trace_id}
        total = self.final_response_ms if self.final_response_ms is not None else round((time.monotonic() - self.started_monotonic) * 1000, 2)
        stages = {"routing_ms": "routing", "memory_retrieval_ms": "memory_search", "decision_ms": "decision",
                  "planner_ms": "planner", "workflow_ms": "workflow", "response_generation_ms": "response_generation",
                  "auto_memory_ms": "memory", "current_cognition_ms": "current_cognition",
                  "context_build_ms": "context_build", "session_persist_ms": "session_persist",
                  "tool_discovery_ms": "tool_discovery", "post_turn_enqueue_ms": "post_turn_enqueue",
                  "response_packaging_ms": "response_packaging"}
        values = {key: round(self.stage_ms.get(stage, 0), 2) for key, stage in stages.items()}
        values["tool_ms_total"] = round(sum(float(call.get("duration_ms") or 0) for call in self.tool_calls), 2)
        # Union of measured intervals: nested model/tool stages are not added twice.
        intervals = sorted(self.intervals)
        covered = 0.0
        end = self.started_monotonic
        for begin, stop in intervals:
            covered += max(0, stop - max(begin, end))
            end = max(end, stop)
        values["other_ms"] = round(max(0, total - covered * 1000), 2)
        values["unclassified_ms"] = values["other_ms"]
        return {"request_id": self.request_id, "trace_id": self.trace_id, "started_at": self.started_at,
                "finished_at": self.finished_at, "total_ms": total, "ttfr_ms": self.first_reply_ms,
                "final_response_ms": self.final_response_ms, "final_reply_ready_ms": self.final_reply_ready_ms, **values,
                "llm_call_count": len(self.llm_calls), "llm_calls": self.llm_calls,
                "foreground_llm_calls": sum(call.get("owner") not in {"auto_memory", "current_cognition"} for call in self.llm_calls),
                "background_llm_calls": sum(call.get("owner") in {"auto_memory", "current_cognition"} for call in self.llm_calls),
                "router_llm_calls": sum(call.get("owner") == "router" for call in self.llm_calls),
                "agent_llm_calls": sum(call.get("owner") in {"agent", "fast_chat"} for call in self.llm_calls),
                "planner_llm_calls": sum(call.get("owner") == "planner" for call in self.llm_calls),
                "tool_call_count": len(self.tool_calls), "tool_calls": self.tool_calls,
                "control_call_count": sum(e.event_type == "control_call_finished" for e in self.events),
                "stage_times_are_inclusive": True,
                "memory_hits": self.memory_hits, "memory_search_count": sum(e.event_type == "memory_search_started" for e in self.events),
                "memory_candidates": self.memory_candidates, "tool_rounds": self.tool_rounds,
                "catalog_inspections": self.catalog_inspections,
                "current_cognition_gate": next((e.metadata for e in reversed(self.events) if e.event_type == "current_cognition_gate"), None),
                "current_cognition_triggered": sum(e.event_type == "current_cognition_triggered" for e in self.events),
                "current_cognition_skipped": sum(e.event_type == "current_cognition_skipped" for e in self.events),
                "current_cognition_model_ms": round(sum(float(e.metadata.get("duration_ms") or 0) for e in self.events if e.event_type == "current_cognition_applied"), 2),
                "current_cognition_ops_count": sum(int(e.metadata.get("ops_count") or 0) for e in self.events if e.event_type == "current_cognition_applied"),
                "threads_added": sum(int(e.metadata.get("threads_added") or 0) for e in self.events if e.event_type == "current_cognition_applied"),
                "threads_updated": sum(int(e.metadata.get("threads_updated") or 0) for e in self.events if e.event_type == "current_cognition_applied"),
                "threads_removed": sum(int(e.metadata.get("threads_removed") or 0) for e in self.events if e.event_type == "current_cognition_applied"),
                "planner_used": self.planner_used, "decision_used": self.decision_used,
                "interim_replies": self.interim_replies,
                "route": self.route, "runtime_lane": self.runtime_lane, "route_source": self.route_source,
                "fast_gate_reason": self.fast_gate_reason, "escalation_reason": self.escalation_reason,
                "fast_escalation_count": self.fast_escalation_count,
                "fast_escalation_kind": self.fast_escalation_kind,
                **self.fast_gate_details,
                "router_required": self.router_required, "router_override": self.router_override,
                "router_final_lane": self.router_final_lane, "router_to_fast_count": self.router_to_fast_count,
                "extra_round_reason": self.extra_round_reason,
                "timeline": [event.payload() for event in self.events]}

    def start_tool(self, name: str, call_id: str, invocation_id: str, step: int | str | None) -> ActionAttempt:
        # A schema rejection cannot have changed external state. A later call to
        # the same tool is its repair; successful writes remain distinct actions.
        previous = self.actions[-1] if self.actions else None
        if (previous is not None and previous.tool_name == name and previous.status == "failed"
                and previous.failure_kind == "validation" and previous.step_id is not None
                and isinstance(step, int) and isinstance(previous.step_id, int)
                and step > previous.step_id):
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
                "actions": [asdict(item) for item in self.actions], "runtime_metrics": self.metrics()}


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

_llm_owner: ContextVar[tuple[str, str]] = ContextVar("zhaoxi_llm_owner", default=("agent", "model"))

@contextmanager
def llm_owner_scope(owner: str, stage: str) -> Iterator[None]:
    token = _llm_owner.set((owner, stage))
    try:
        yield
    finally:
        _llm_owner.reset(token)

def current_llm_owner() -> tuple[str, str]:
    return _llm_owner.get()


@contextmanager
def bind_action_trace(trace: ActionTrace) -> Iterator[None]:
    """Associate post-response work with the same request without reopening it."""
    token = _current.set(trace)
    try:
        yield
    finally:
        _current.reset(token)
