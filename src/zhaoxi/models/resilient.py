"""Bounded retry, fallback, circuit breaking, and call budgeting for providers."""

from __future__ import annotations

from typing import Any, Sequence

from zhaoxi.core.message import Message
from zhaoxi.errors import ProviderError
from zhaoxi.models.base import ModelProvider
from zhaoxi.models.types import ModelResponse
from zhaoxi.reliability.metrics import MetricRegistry
from zhaoxi.reliability.retry import (
    CircuitBreaker,
    RetryPolicy,
    consume_provider_budget,
    record_provider_tokens,
    retry_async,
)


class ResilientProvider(ModelProvider):
    def __init__(
        self,
        providers: list[ModelProvider],
        *,
        retry_policy: RetryPolicy | None = None,
        failure_threshold: int = 5,
        cooldown_seconds: float = 60,
        max_calls: int = 12,
        max_total_tokens: int = 100_000,
        metrics: MetricRegistry | None = None,
        sleeper=None,
    ) -> None:
        if not providers:
            raise ValueError("至少需要一个 Provider")
        self.providers = providers
        self.retry_policy = retry_policy or RetryPolicy()
        self.breakers = [CircuitBreaker(failure_threshold, cooldown_seconds) for _ in providers]
        self.max_calls = max_calls
        self.max_total_tokens = max_total_tokens
        self.metrics = metrics or MetricRegistry()
        self.sleeper = sleeper

    async def generate(
        self,
        messages: Sequence[Message],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        last_error: ProviderError | None = None
        for index, (provider, breaker) in enumerate(zip(self.providers, self.breakers, strict=True)):
            if not breaker.allow():
                self.metrics.increment("provider.circuit_open")
                continue

            async def invoke():
                consume_provider_budget()
                self.metrics.increment("provider.calls")
                return await provider.generate(messages, tools, **kwargs)

            try:
                options = {
                    "policy": self.retry_policy,
                    "should_retry": lambda exc: isinstance(exc, ProviderError) and exc.retryable,
                }
                if self.sleeper is not None:
                    options["sleeper"] = self.sleeper
                result = await retry_async(invoke, **options)
                record_provider_tokens(int(result.usage.get("total_tokens", 0) or 0))
                breaker.success()
                if index:
                    self.metrics.increment("provider.fallback_success")
                return result
            except ProviderError as exc:
                last_error = exc
                if exc.retryable:
                    breaker.failure()
                    self.metrics.increment("provider.transient_failure")
                    if index + 1 < len(self.providers):
                        self.metrics.increment("provider.fallback")
                        continue
                raise
        if last_error is not None:
            raise last_error
        raise ProviderError("所有模型 Provider 当前均处于熔断状态。", code="all_providers_open", retryable=True)
