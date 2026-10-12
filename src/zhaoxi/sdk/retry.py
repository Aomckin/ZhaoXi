"""Small public retry primitive for capability packages."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0
    jitter_ratio: float = 0.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts 必须至少为 1")
        if self.base_delay_seconds < 0 or self.max_delay_seconds < 0:
            raise ValueError("retry delay 不能为负数")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("jitter_ratio 必须在 0 到 1 之间")

    def delay(self, failed_attempt: int, *, random_value: float | None = None) -> float:
        base = min(self.max_delay_seconds, self.base_delay_seconds * (2 ** (failed_attempt - 1)))
        if not self.jitter_ratio:
            return base
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
