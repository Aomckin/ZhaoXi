"""Deterministic retry, request-budget, and circuit-breaker primitives."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from time import monotonic
from typing import TypeVar

from zhaoxi.errors import ProviderError

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0
    jitter_ratio: float = 0.1

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts 必须至少为 1")
        if self.base_delay_seconds < 0 or self.max_delay_seconds < 0:
            raise ValueError("retry delay 不能为负数")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("jitter_ratio 必须在 0 到 1 之间")

    def delay(self, failed_attempt: int, *, random_value: float | None = None) -> float:
        base = min(self.max_delay_seconds, self.base_delay_seconds * (2 ** (failed_attempt - 1)))
        value = random.random() if random_value is None else random_value
        return max(0.0, base * (1 + self.jitter_ratio * (value * 2 - 1)))


async def retry_async(
    operation: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy,
    should_retry: Callable[[Exception], bool],
    sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return await operation()
        except Exception as exc:
            if attempt >= policy.max_attempts or not should_retry(exc):
                raise
            await sleeper(policy.delay(attempt))
    raise AssertionError("unreachable")


@dataclass(slots=True)
class CallBudget:
    max_calls: int
    max_total_tokens: int
    calls: int = 0
    total_tokens: int = 0

    def consume(self) -> None:
        if self.calls >= self.max_calls:
            raise ProviderError(
                "本次任务的模型调用预算已用完。",
                code="provider_call_budget_exhausted",
                retryable=False,
            )
        self.calls += 1

    def record_tokens(self, tokens: int) -> None:
        self.total_tokens += max(0, tokens)
        if self.total_tokens > self.max_total_tokens:
            raise ProviderError(
                "本次任务的 Token 预算已用完。",
                code="provider_token_budget_exhausted",
                retryable=False,
            )


_budget: ContextVar[CallBudget | None] = ContextVar("zhaoxi_provider_budget", default=None)


@contextmanager
def provider_budget_scope(max_calls: int, max_total_tokens: int = 100_000):
    token = _budget.set(CallBudget(max_calls=max_calls, max_total_tokens=max_total_tokens))
    try:
        yield _budget.get()
    finally:
        _budget.reset(token)


def consume_provider_budget() -> None:
    budget = _budget.get()
    if budget is not None:
        budget.consume()


def record_provider_tokens(tokens: int) -> None:
    budget = _budget.get()
    if budget is not None:
        budget.record_tokens(tokens)


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 60) -> None:
        if failure_threshold < 1 or cooldown_seconds < 0:
            raise ValueError("circuit breaker 配置无效")
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.failures = 0
        self.opened_at: float | None = None

    @property
    def state(self) -> CircuitState:
        if self.opened_at is None:
            return CircuitState.CLOSED
        if monotonic() - self.opened_at >= self.cooldown_seconds:
            return CircuitState.HALF_OPEN
        return CircuitState.OPEN

    def allow(self) -> bool:
        return self.state is not CircuitState.OPEN

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.opened_at = monotonic()
