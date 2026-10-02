"""Explicit presence, resource and message permissions for activities."""
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable, Awaitable, Any

class PresenceState(StrEnum):
    ACTIVE = "ACTIVE"
    SEMI_ACTIVE = "SEMI_ACTIVE"
    IDLE = "IDLE"
    AWAY = "AWAY"
    SLEEP = "SLEEP"

class ActivityCategory(StrEnum):
    MAINTENANCE = "MAINTENANCE"
    COGNITION = "COGNITION"
    MEMORY = "MEMORY"
    SOCIAL = "SOCIAL"
    LEISURE = "LEISURE"
    PROACTIVE = "PROACTIVE"
    LOCAL = "LOCAL"

class CostClass(StrEnum):
    LOCAL_LIGHT = "LOCAL_LIGHT"
    LOCAL_HEAVY = "LOCAL_HEAVY"
    LLM_LIGHT = "LLM_LIGHT"
    LLM_HEAVY = "LLM_HEAVY"
    EXTERNAL_READ = "EXTERNAL_READ"
    EXTERNAL_WRITE = "EXTERNAL_WRITE"

@dataclass
class ActivityResult:
    status: str = "NO_CHANGE"
    changed: bool = False
    message_sent: bool = False
    cost: dict[str, int] = field(default_factory=dict)
    summary: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    deliveries: list = field(default_factory=list)

    def diagnostics(self):
        return {key: value for key, value in vars(self).items() if key != "deliveries"}

@dataclass(frozen=True)
class ActivitySpec:
    name: str
    category: ActivityCategory
    cost_class: CostClass
    presence_states: frozenset[PresenceState]
    priority: int
    min_interval: float
    handler: Callable[[Any, str], Awaitable]
    candidate: Callable[[Any, Any], Awaitable]
    enabled_setting: str = ""
    requires_llm: bool = False
    requires_external_io: bool = False
    can_message_user: bool = False
    can_message_external: bool = False
    daily_limit_setting: str = ""
    label: str = ""
    preemptible: bool = True

    @property
    def cooldown(self):
        return self.min_interval
