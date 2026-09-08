"""Provider-neutral state signals and deterministic aggregation."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class SignalPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


_PRIORITY_WEIGHT = {
    SignalPriority.LOW: 0,
    SignalPriority.NORMAL: 1,
    SignalPriority.HIGH: 2,
    SignalPriority.CRITICAL: 3,
}


class StateSignal(BaseModel):
    type: str = Field(min_length=1, max_length=160)
    value: Any
    observed_at: datetime
    expires_at: datetime
    confidence: float = Field(default=1.0, ge=0, le=1)
    priority: SignalPriority = SignalPriority.NORMAL
    source: str = Field(min_length=1, max_length=120)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_times(self) -> "StateSignal":
        if self.observed_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("StateSignal timestamps must include a timezone")
        self.observed_at = self.observed_at.astimezone(UTC)
        self.expires_at = self.expires_at.astimezone(UTC)
        return self


class SignalAggregator:
    """Merge fresh observations without knowing any concrete provider."""

    def __init__(self) -> None:
        self._signals: dict[tuple[str, str], StateSignal] = {}

    def update(self, signals: list[StateSignal], now: datetime) -> None:
        self.expire(now)
        for signal in signals:
            if signal.expires_at > now:
                self._signals[(signal.type, signal.source)] = signal

    def expire(self, now: datetime) -> None:
        self._signals = {
            key: signal for key, signal in self._signals.items()
            if signal.expires_at > now
        }

    def resolve(self, signal_type: str, now: datetime) -> StateSignal | None:
        self.expire(now)
        candidates = [signal for signal in self._signals.values() if signal.type == signal_type]
        return max(
            candidates,
            key=lambda item: (_PRIORITY_WEIGHT[item.priority], item.confidence, item.observed_at),
            default=None,
        )

    def snapshot(self, now: datetime) -> list[dict[str, Any]]:
        self.expire(now)
        return [
            {
                "type": signal.type,
                "value": signal.value,
                "source": signal.source,
                "confidence": signal.confidence,
                "priority": signal.priority.value,
                "observed_at": signal.observed_at,
                "expires_at": signal.expires_at,
            }
            for signal in sorted(self._signals.values(), key=lambda item: (item.type, item.source))
        ]
