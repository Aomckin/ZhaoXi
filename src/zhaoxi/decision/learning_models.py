"""Source-backed summary indexes and provisional experience have separate types."""
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, field_validator


def now():
    return datetime.now(UTC)


class FeedbackLabel(StrEnum):
    GOOD = "GOOD"
    BAD = "BAD"
    NEUTRAL = "NEUTRAL"
    MIXED = "MIXED"
    NO_DIFFERENCE = "NO_DIFFERENCE"
    UNKNOWN = "UNKNOWN"


class FollowUpPolicy(StrEnum):
    NEVER = "NEVER"
    PASSIVE = "PASSIVE"
    OPPORTUNISTIC = "OPPORTUNISTIC"
    SCHEDULED = "SCHEDULED"


class LearningModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class UserPrinciple(LearningModel):
    id: str = Field(pattern=r"^[\w-]+$", max_length=100)
    type: Literal["user_principle"] = "user_principle"
    origin: Literal["owner", "zhaoxi_summary"] = "owner"
    updated_at: datetime | None = None
    statement: str = Field(min_length=1, max_length=1200)
    domain: str = Field(default="general", max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=20)
    confidence: float = Field(default=1, ge=0, le=1)
    source: dict[str, str]
    status: Literal["active", "retired"] = "active"


class DecisionJournalEntry(LearningModel):
    id: str = Field(default_factory=lambda: "DJ-" + uuid4().hex[:16], max_length=100)
    domain: str = Field(default="general", max_length=100)
    title: str = Field(min_length=1, max_length=200)
    statement: str = Field(min_length=1, max_length=1200)
    rationale: str = Field(default="", max_length=1200)
    conditions: list[str] = Field(default_factory=list, max_length=20)
    exceptions: list[str] = Field(default_factory=list, max_length=20)
    confidence: float = Field(default=.5, ge=0, le=1)
    support_count: int = Field(default=0, ge=0)
    conflict_count: int = Field(default=0, ge=0)
    feedback_summary: str = Field(default="", max_length=1200)
    source_decision_ids: list[str] = Field(default_factory=list, max_length=200)
    source_feedback_ids: list[str] = Field(default_factory=list, max_length=200)
    last_reviewed_at: datetime = Field(default_factory=now)
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
    @field_validator("last_reviewed_at", "created_at", "updated_at")
    @classmethod
    def timestamps(cls, value):
        return aware_time(value)

    status: Literal["ACTIVE", "UNCERTAIN", "CONFLICTED", "STALE", "RETIRED"] = "UNCERTAIN"
    manual_state: Literal["NORMAL", "PINNED", "LOCKED", "RETIRED"] = "NORMAL"


class DecisionReflection(LearningModel):
    id: str = Field(default_factory=lambda: "DR-" + uuid4().hex)
    decision_id: str = Field(max_length=64)
    feedback_id: str = Field(default="", max_length=100)
    learnable: bool = False
    summary: str = Field(default="", max_length=1200)
    lessons: list[str] = Field(default_factory=list, max_length=10)
    conditions: list[str] = Field(default_factory=list, max_length=20)
    exceptions: list[str] = Field(default_factory=list, max_length=20)
    journal_action: Literal["NONE", "CREATE", "SUPPORT", "REFINE", "WEAKEN", "CONFLICT", "RETIRE"] = "NONE"
    target_journal_id: str | None = Field(default=None, max_length=100)
    confidence_delta: float = Field(default=0, ge=-1, le=1)
    reason: str = Field(default="", max_length=1200)
    title: str = Field(default="", max_length=200)
    domain: str = Field(default="general", max_length=100)
    statement: str = Field(default="", max_length=1200)
    source_decision_ids: list[str] = Field(default_factory=list, max_length=10)
    principle_conflicts: list[str] = Field(default_factory=list, max_length=10)
    timestamp: datetime = Field(default_factory=now)


def private_owner() -> bool:
    from zhaoxi.cognitive_stream.turn import current_turn
    turn = current_turn()
    return turn is None or (turn.audience == "owner" and
        turn.trigger_event.privacy_level in {"PRIVATE", "OWNER_PRIVATE"} and
        turn.trigger_event.metadata.get("conversation_kind", turn.trigger_event.metadata.get("conversation_type")) != "group")


def require_owner():
    if not private_owner():
        raise PermissionError("个人决策资料仅供 Owner 私密会话使用。")


def aware_time(value: datetime | None):
    if value is not None and value.tzinfo is None:
        raise ValueError("时间须包含时区")
    return value.astimezone(UTC) if value else None
