"""Domain models for deterministic proactive events and scheduling."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator, computed_field


def utc_now() -> datetime:
    return datetime.now(UTC)


class Priority(StrEnum):
    INFO = "info"
    NOTICE = "notice"
    IMPORTANT = "important"
    URGENT = "urgent"


class EventStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    HANDLED = "handled"
    FAILED = "failed"


class ScheduleKind(StrEnum):
    ONCE = "once"
    INTERVAL = "interval"


class MisfirePolicy(StrEnum):
    SKIP = "skip"
    FIRE_ONCE = "fire_once"
    EXPIRE = "expire"


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    DEFERRED = "deferred"
    DELIVERED = "delivered"
    ACKNOWLEDGED = "acknowledged"
    SUPPRESSED = "suppressed"
    EXPIRED = "expired"
    FAILED = "failed"


class PolicyAction(StrEnum):
    DELIVER_NOW = "deliver_now"
    DEFER = "defer"
    INBOX_ONLY = "inbox_only"
    SUPPRESS = "suppress"


class Subscription(BaseModel):
    subscription_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$")
    event_type: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$")
    condition: dict[str, Any] | None = None
    notification_template: str = "{event_type}"
    default_priority: Priority = Priority.NOTICE
    enabled: bool = True
    cooldown_seconds: int = Field(default=0, ge=0)


class PolicyDecision(BaseModel):
    action: PolicyAction
    reason: str
    defer_until: datetime | None = None


class ProactiveEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: uuid4().hex, pattern=r"^[A-Za-z0-9_.:-]+$")
    schema_version: int = Field(default=1, ge=1)
    event_type: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    source: str = Field(min_length=1, max_length=120)
    occurred_at: datetime = Field(default_factory=utc_now)
    received_at: datetime = Field(default_factory=utc_now)
    priority: Priority = Priority.NOTICE
    dedupe_key: str | None = Field(default=None, max_length=240)
    correlation_id: str | None = Field(default=None, max_length=120)
    payload: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None
    status: EventStatus = EventStatus.PENDING
    attempts: int = Field(default=0, ge=0)
    last_error: str | None = Field(default=None, max_length=500)
    importance: float = Field(default=0.65, ge=0, le=1)
    urgency: float = Field(default=0.4, ge=0, le=1)
    next_decision_at: datetime | None = None

    @model_validator(mode="after")
    def normalize_times(self) -> "ProactiveEvent":
        for name in ("occurred_at", "received_at", "expires_at", "next_decision_at"):
            value = getattr(self, name)
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{name} 必须包含时区")
            if value is not None:
                setattr(self, name, value.astimezone(UTC))
        return self

    @property
    def event_at(self) -> datetime:
        """Canonical event time; compatibility name remains occurred_at."""
        return self.occurred_at

    @property
    def recorded_at(self) -> datetime:
        """Time the event entered Zhaoxi, not the time it happened."""
        return self.received_at

    @property
    def known_at(self) -> datetime:
        """For ingested events, first-known time equals received_at."""
        return self.received_at


class Schedule(BaseModel):
    schedule_id: str = Field(default_factory=lambda: uuid4().hex, pattern=r"^[A-Za-z0-9_.:-]+$")
    event_type: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    source: str = Field(default="scheduler", min_length=1, max_length=120)
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: Priority = Priority.NOTICE
    kind: ScheduleKind
    next_fire_at: datetime
    interval_seconds: int | None = Field(default=None, ge=1)
    timezone: str = "Asia/Shanghai"
    misfire_policy: MisfirePolicy = MisfirePolicy.FIRE_ONCE
    enabled: bool = True
    last_fired_at: datetime | None = None
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_schedule(self) -> "Schedule":
        if self.next_fire_at.tzinfo is None:
            raise ValueError("next_fire_at 必须包含时区")
        self.next_fire_at = self.next_fire_at.astimezone(UTC)
        if self.last_fired_at is not None:
            if self.last_fired_at.tzinfo is None:
                raise ValueError("last_fired_at 必须包含时区")
            self.last_fired_at = self.last_fired_at.astimezone(UTC)
        if self.kind == ScheduleKind.INTERVAL and self.interval_seconds is None:
            raise ValueError("interval 调度必须声明 interval_seconds")
        if self.kind == ScheduleKind.ONCE and self.interval_seconds is not None:
            raise ValueError("once 调度不能声明 interval_seconds")
        return self


class Delivery(BaseModel):
    delivery_id: str = Field(default_factory=lambda: uuid4().hex)
    event_id: str
    subscription_id: str
    priority: Priority
    status: DeliveryStatus = DeliveryStatus.PENDING
    decision_reason: str = ""
    content: str = ""
    available_at: datetime = Field(default_factory=utc_now)
    delivered_at: datetime | None = None
    acknowledged_at: datetime | None = None
    attempts: int = Field(default=0, ge=0)
    event_type: str = ""
    relevant_payload: dict[str, Any] = Field(default_factory=dict)
    related_event_ids: list[str] = Field(default_factory=list)


    @computed_field
    @property
    def kind(self) -> str:
        """Route factual notices separately from conversational initiative."""
        return 'system' if (self.event_type.startswith('system.')
            or self.event_type in {'task.completed', 'reminder.due'}
            or self.decision_reason == 'inbox') else 'assistant'
