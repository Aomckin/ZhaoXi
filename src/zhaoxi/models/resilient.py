"""Bounded retry, fallback, circuit breaking, and call budgeting for providers."""

from __future__ import annotations

from typing import Any, Sequence
from datetime import UTC, datetime
from time import monotonic

from zhaoxi.observability import current_trace, current_llm_owner

from zhaoxi.core.message import Message
from zhaoxi.errors import ProviderError
from zhaoxi.models.base import ModelProvider
from zhaoxi.models.types import ModelResponse
from zhaoxi.reliability.metrics import MetricRegistry
from zhaoxi.reliability.retry import (
    BudgetPolicy,
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
        budget_policy: BudgetPolicy | None = None,
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
        self.budget_policy = budget_policy
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
                trace = current_trace()
                owner, stage = current_llm_owner()
                started_at = datetime.now(UTC).isoformat()
                started = monotonic()
                if trace and trace.metrics_enabled:
                    trace.emit("llm_call_started", "model", "running", "正在调用模型…",
                               metadata={"index": len(trace.llm_calls) + 1, "owner": owner, "stage": stage})
                response = None
                try:
                    response = await provider.generate(messages, tools, **kwargs)
                    return response
                finally:
                    if trace and trace.metrics_enabled:
                        usage = response.usage if response is not None else {}
                        item = {"index": len(trace.llm_calls) + 1, "owner": owner, "stage": stage,
                                "started_at": started_at, "finished_at": datetime.now(UTC).isoformat(),
                                "duration_ms": round((monotonic() - started) * 1000, 2),
                                "prompt_tokens": usage.get("prompt_tokens", usage.get("input_tokens")),
                                "output_tokens": usage.get("completion_tokens", usage.get("output_tokens")),
                                "total_tokens": usage.get("total_tokens"),
                                "tool_call_count": len(response.tool_calls) if response else 0,
                                "finish_reason": response.finish_reason if response else None}
                        trace.llm_calls.append(item)
                        trace.emit("llm_call_finished", "model", "success" if response else "failed",
                                   "模型调用已结束" if response else "模型调用失败", metadata=item)

            try:
                options = {
                    "policy": self.retry_policy,
                    "should_retry": lambda exc: isinstance(exc, ProviderError) and exc.retryable,
                }
                if self.sleeper is not None:
                    options["sleeper"] = self.sleeper
                result = await retry_async(invoke, **options)
                usage = result.usage
                input_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
                output_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
                call_total = usage.get("total_tokens")
                if call_total is None:
                    call_total = (int(input_tokens or 0) + int(output_tokens or 0))
                record_provider_tokens(int(call_total or 0),
                                       input_tokens=int(input_tokens) if input_tokens is not None else None,
                                       output_tokens=int(output_tokens) if output_tokens is not None else None,
                                       provider=type(provider).__name__,
                                       model=str(result.raw_metadata.get("model") or getattr(provider, "model", "unknown")))
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
