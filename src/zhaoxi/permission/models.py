"""Provider-neutral permission domain models."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class PermissionLevel(StrEnum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    EXTERNAL_ACTION = "external_action"
    DANGEROUS = "dangerous"


class SideEffect(StrEnum):
    NONE = "none"
    LOCAL_STATE = "local_state"
    DATA_DELETION = "data_deletion"
    EXTERNAL_COMMUNICATION = "external_communication"
    SYSTEM_CHANGE = "system_change"


class PermissionStatus(StrEnum):
    ALLOW = "allow"
    REQUIRE_CONFIRMATION = "require_confirmation"
    DENY = "deny"


class InvocationOrigin(StrEnum):
    AGENT = "agent"
    PLANNER = "planner"
    AUTO_MEMORY = "auto_memory"
    USER_COMMAND = "user_command"


class PermissionRequest(BaseModel):
    invocation_id: str = Field(default_factory=lambda: uuid4().hex)
    request_id: str
    tool_name: str
    permission: PermissionLevel
    arguments: dict[str, Any]
    arguments_digest: str
    resource_scope: str
    action_summary: str
    origin: InvocationOrigin
    user_intent: str = ""
    goal_id: str | None = None
    step_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PermissionDecision(BaseModel):
    status: PermissionStatus
    reason_code: str


class PendingConfirmation(BaseModel):
    confirmation_id: str = Field(default_factory=lambda: uuid4().hex)
    request: PermissionRequest
    question: str
    risk_summary: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    resolved: bool = False
    approved: bool | None = None


class PermissionGrant(BaseModel):
    grant_id: str = Field(default_factory=lambda: uuid4().hex)
    confirmation_id: str
    invocation_id: str
    tool_name: str
    arguments_digest: str
    resource_scope: str
    expires_at: datetime
    max_uses: int = 1
    uses: int = 0
    revoked: bool = False


class AuditEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    event_type: str
    invocation_id: str
    request_id: str
    tool_name: str
    permission: PermissionLevel
    origin: InvocationOrigin
    goal_id: str | None = None
    step_id: str | None = None
    reason_code: str | None = None
    arguments_digest: str
    resource_scope: str
    result_status: str | None = None
