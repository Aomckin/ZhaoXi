"""Validated workflow definitions and runtime state."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class WorkflowStepType(StrEnum):
    TOOL = "tool"
    CONDITION = "condition"
    ASK = "ask"
    SET = "set"
    END = "end"


class WorkflowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_INPUT = "waiting_for_input"
    WAITING_FOR_PERMISSION = "waiting_for_permission"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowStepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


TERMINAL_WORKFLOW_STATUSES = {
    WorkflowStatus.COMPLETED,
    WorkflowStatus.FAILED,
    WorkflowStatus.CANCELLED,
}


class WorkflowInput(BaseModel):
    type: str = "string"
    required: bool = False
    default: Any = None
    description: str = ""
    sensitive: bool = False


class RetryPolicy(BaseModel):
    max_attempts: int = Field(default=1, ge=1, le=10)


class WorkflowStep(BaseModel):
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    type: WorkflowStepType
    tool: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    expression: Any = None
    question: str | None = None
    fields: list[str] = Field(default_factory=list)
    values: dict[str, Any] = Field(default_factory=dict)
    output_mapping: dict[str, str] = Field(default_factory=dict)
    next: str | None = None
    on_true: str | None = None
    on_false: str | None = None
    on_failure: str | None = None
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    result: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_shape(self) -> "WorkflowStep":
        if self.type == WorkflowStepType.TOOL and not self.tool:
            raise ValueError("tool 步骤必须声明 tool")
        if self.type == WorkflowStepType.CONDITION and self.expression is None:
            raise ValueError("condition 步骤必须声明 expression")
        if self.type == WorkflowStepType.ASK and (not self.question or not self.fields):
            raise ValueError("ask 步骤必须声明 question 和 fields")
        return self


class WorkflowDefinition(BaseModel):
    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    version: int = Field(ge=1)
    name: str = Field(min_length=1)
    description: str = ""
    aliases: list[str] = Field(default_factory=list)
    inputs: dict[str, WorkflowInput] = Field(default_factory=dict)
    steps: list[WorkflowStep] = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True


class WorkflowStepRun(BaseModel):
    step_id: str
    status: WorkflowStepStatus = WorkflowStepStatus.PENDING
    attempts: int = 0
    invocation_id: str | None = None
    confirmation_id: str | None = None
    output: Any = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class WorkflowEvent(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    type: str
    step_id: str | None = None
    timestamp: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowRun(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    workflow_id: str
    workflow_version: int
    user_intent: str = ""
    definition_snapshot: WorkflowDefinition
    status: WorkflowStatus = WorkflowStatus.PENDING
    current_step_id: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    ignored_inputs: list[str] = Field(default_factory=list)
    variables: dict[str, Any] = Field(default_factory=dict)
    step_runs: list[WorkflowStepRun] = Field(default_factory=list)
    pending_fields: list[str] = Field(default_factory=list)
    pending_question: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    events: list[WorkflowEvent] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None

    def step_run(self, step_id: str) -> WorkflowStepRun:
        return next(item for item in self.step_runs if item.step_id == step_id)

    def record(self, event_type: str, step_id: str | None = None, **metadata: Any) -> None:
        self.events.append(WorkflowEvent(type=event_type, step_id=step_id, metadata=metadata))
        self.updated_at = utc_now()
