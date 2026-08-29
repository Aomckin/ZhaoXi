"""Validated planner state and transition rules."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from zhaoxi.errors import InvalidStateTransitionError


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class GoalStatus(StrEnum):
    PENDING = "pending"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_FOR_USER = "waiting_for_user"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


TERMINAL_GOAL_STATUSES = {GoalStatus.COMPLETED, GoalStatus.FAILED, GoalStatus.CANCELLED}

GOAL_TRANSITIONS = {
    GoalStatus.PENDING: {GoalStatus.PLANNING, GoalStatus.CANCELLED},
    GoalStatus.PLANNING: {GoalStatus.RUNNING, GoalStatus.WAITING_FOR_USER, GoalStatus.FAILED, GoalStatus.CANCELLED},
    GoalStatus.RUNNING: {GoalStatus.PLANNING, GoalStatus.WAITING_FOR_USER, GoalStatus.COMPLETED, GoalStatus.FAILED, GoalStatus.CANCELLED},
    GoalStatus.WAITING_FOR_USER: {GoalStatus.PLANNING, GoalStatus.RUNNING, GoalStatus.CANCELLED},
}

STEP_TRANSITIONS = {
    StepStatus.PENDING: {StepStatus.RUNNING, StepStatus.SKIPPED, StepStatus.CANCELLED},
    StepStatus.RUNNING: {StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.PENDING, StepStatus.CANCELLED},
    StepStatus.FAILED: {StepStatus.PENDING, StepStatus.SKIPPED, StepStatus.CANCELLED},
}


class PlanStep(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    description: str = Field(min_length=1)
    status: StepStatus = StepStatus.PENDING
    attempt_count: int = Field(default=0, ge=0)
    tool_attempts: dict[str, int] = Field(default_factory=dict)
    tool_hints: list[str] = Field(default_factory=list)
    result_summary: str | None = None

    def transition(self, target: StepStatus) -> None:
        if target == self.status:
            return
        if target not in STEP_TRANSITIONS.get(self.status, set()):
            raise InvalidStateTransitionError(f"步骤不能从 {self.status} 变为 {target}。")
        self.status = target


class Plan(BaseModel):
    goal_id: str
    revision: int = Field(ge=1)
    steps: list[PlanStep] = Field(min_length=1)
    reason: str = "initial plan"
    created_at: datetime = Field(default_factory=utc_now)


class Observation(BaseModel):
    step_id: str | None = None
    tool_name: str
    success: bool
    content: str
    data: Any = None
    error: str | None = None
    retryable: bool = False
    timestamp: datetime = Field(default_factory=utc_now)


class InputRequest(BaseModel):
    goal_id: str
    question: str = Field(min_length=1)
    missing_fields: list[str] = Field(default_factory=list)
    resume_token: str = Field(default_factory=lambda: uuid4().hex)


class Goal(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    description: str = Field(min_length=1)
    status: GoalStatus = GoalStatus.PENDING
    plans: list[Plan] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    input_request: InputRequest | None = None
    final_content: str | None = None
    replan_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @property
    def current_plan(self) -> Plan | None:
        return self.plans[-1] if self.plans else None

    def transition(self, target: GoalStatus) -> None:
        if target == self.status:
            return
        if self.status in TERMINAL_GOAL_STATUSES or target not in GOAL_TRANSITIONS.get(self.status, set()):
            raise InvalidStateTransitionError(f"任务不能从 {self.status} 变为 {target}。")
        self.status = target
        self.updated_at = utc_now()


class TraceEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    trace_id: str
    goal_id: str
    plan_revision: int | None = None
    step_id: str | None = None
    event_type: str
    timestamp: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)
