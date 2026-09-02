"""LifeHUD-Tool contracts for Agent Context schema 1."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LifeHudModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class AgentEnvelope(LifeHudModel):
    schemaVersion: Literal["1"]
    generatedAt: datetime

    @field_validator("generatedAt")
    @classmethod
    def generated_at_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("generatedAt 必须包含时区")
        return value


class FocusSession(LifeHudModel):
    id: str
    mode: Literal["IRON_CURTAIN", "POMODORO", "FREE"]
    status: Literal["RUNNING", "PAUSED", "COMPLETED", "INTERRUPTED"]
    title: str
    taskId: str | None = None
    startedAt: datetime
    endedAt: datetime | None = None
    plannedMinutes: int | None = None
    actualSeconds: int = 0
    actualMinutes: int = 0
    effectiveSeconds: int = 0
    effectiveMinutes: int = 0
    note: str | None = None
    updatedAt: datetime | None = None
    relatedTaskIds: list[str] = Field(default_factory=list)
    segments: list[dict[str, Any]] = Field(default_factory=list)
    breakMinutes: int = 5

    @field_validator("startedAt", "endedAt", "updatedAt")
    @classmethod
    def instant_has_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Instant 必须包含时区")
        return value


class CheckIn(LifeHudModel):
    id: str
    energy: int
    mood: int
    focusDesire: int
    fatigue: int
    time: datetime
    note: str = ""
    images: list[str] = Field(default_factory=list)
    createdAt: datetime
    updatedAt: datetime


class Status(LifeHudModel):
    energy: int
    level: int
    exp: int
    title: str
    checkIn: CheckIn | None = None
    activeFocus: FocusSession | None = None


class DailyFocus(LifeHudModel):
    date: date
    effectiveMinutes: int


class Focus(LifeHudModel):
    effectiveMinutes: int
    sessionCount: int
    active: FocusSession | None = None
    recent: list[FocusSession] = Field(default_factory=list)
    daily: list[DailyFocus] = Field(default_factory=list)


class TaskItem(LifeHudModel):
    id: str
    name: str
    completed: bool
    special: bool
    dreamId: str | None = None
    goalId: str | None = None
    milestoneId: str | None = None


class Tasks(LifeHudModel):
    completed: int
    remaining: int
    items: list[TaskItem] = Field(default_factory=list)


class TimelineItem(LifeHudModel):
    eventId: str
    type: str
    source: str
    sourceId: str | None = None
    occurredAt: datetime
    title: str
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    media: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Dreams(LifeHudModel):
    active: list[dict[str, Any]] = Field(default_factory=list)
    goals: list[dict[str, Any]] = Field(default_factory=list)
    milestones: list[dict[str, Any]] = Field(default_factory=list)


class Rituals(LifeHudModel):
    completedToday: list[dict[str, Any]] = Field(default_factory=list)
    available: list[dict[str, Any]] = Field(default_factory=list)


class Media(LifeHudModel):
    watchingAnime: list[dict[str, Any]] = Field(default_factory=list)
    playingGames: list[dict[str, Any]] = Field(default_factory=list)
    animeSessions: list[dict[str, Any]] = Field(default_factory=list)
    gameSessions: list[dict[str, Any]] = Field(default_factory=list)
    items: list[dict[str, Any]] = Field(default_factory=list)
    recentlyCompleted: list[dict[str, Any]] = Field(default_factory=list)


class TodayContext(AgentEnvelope):
    date: date
    status: Status
    focus: Focus
    tasks: Tasks
    sleep: dict[str, Any] | None = None
    meal: dict[str, Any] | None = None
    dreams: Dreams
    rituals: Rituals
    media: Media
    timeline: list[TimelineItem] = Field(default_factory=list)


class RecentContext(AgentEnvelope):
    startDate: date
    endDate: date
    days: int
    lifeEventCount: int
    focusMinutes: int
    tasksCompleted: int
    timeline: list[TimelineItem] = Field(default_factory=list)


class StatusContext(AgentEnvelope):
    status: Status


class FocusContext(AgentEnvelope):
    date: date
    focus: Focus


class TasksContext(AgentEnvelope):
    date: date
    tasks: Tasks


class DreamsContext(AgentEnvelope):
    dreams: Dreams


class LifeContext(AgentEnvelope):
    date: date
    life: dict[str, Any]


class JournalContext(AgentEnvelope):
    entries: list[dict[str, Any]] = Field(default_factory=list)
    timeline: list[TimelineItem] = Field(default_factory=list)


class MediaContext(AgentEnvelope):
    media: Media


class GrowthContext(AgentEnvelope):
    growth: dict[str, Any]


class FocusStartInput(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    related_task_ids: list[str] = Field(default_factory=list)


class FocusCurrentInput(BaseModel):
    pass


class FocusCompleteInput(BaseModel):
    session_id: str = Field(min_length=1)
    note: str | None = Field(default=None, max_length=4000)


class RecentInput(BaseModel):
    days: int = Field(default=7, ge=1, le=30)


class JournalInput(BaseModel):
    limit: int = Field(default=20, ge=1, le=100)


class EmptyInput(BaseModel):
    pass
