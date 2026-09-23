"""Deterministic retry, request-budget, and circuit-breaker primitives."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import StrEnum
from time import monotonic
from typing import TypeVar

from zhaoxi.errors import ProviderError

budget_logger = logging.getLogger("TOKEN_BUDGET")

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


@dataclass(frozen=True, slots=True)
class BudgetPolicy:
    base_budget: int
    extension_1_limit: int
    extension_2_limit: int
    hard_limit: int
    finalization_reserve: int
    warning_ratio: float = 0.85

    def __post_init__(self) -> None:
        if not 0 < self.base_budget <= self.hard_limit:
            raise ValueError("Budget base/hard limit 无效")
        if self.extension_1_limit < 0 or self.extension_2_limit < 0:
            raise ValueError("Budget extension 不能为负数")
        if not 0 <= self.finalization_reserve < self.base_budget:
            raise ValueError("Finalization reserve 必须小于 Base Budget")
        if not 0 < self.warning_ratio < 1:
            raise ValueError("Budget warning ratio 无效")


@dataclass(frozen=True, slots=True)
class BudgetExtensionRequest:
    reason: str
    remaining_actions: int
    estimated_extra_tokens: int
    stage: str
    progress_evidence: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.reason.strip() or len(self.reason) > 240:
            raise ValueError("Budget extension reason 无效")
        if self.remaining_actions < 0 or self.estimated_extra_tokens <= 0:
            raise ValueError("Budget extension 规模无效")
        if self.stage not in {"planning", "tool_execution", "recovery", "finalization"}:
            raise ValueError("Budget extension stage 无效")


@dataclass(slots=True)
class CallBudget:
    max_calls: int
    max_total_tokens: int
    calls: int = 0
    total_tokens: int = 0
    policy: BudgetPolicy | None = None
    extension_count: int = 0
    stage_usage: dict[str, int] = field(default_factory=dict)
    context_reports: list[dict[str, object]] = field(default_factory=list)
    extension_history: list[dict[str, object]] = field(default_factory=list)
    reserve_entered: bool = False

    @property
    def hard_limit(self) -> int:
        return self.policy.hard_limit if self.policy else self.max_total_tokens

    @property
    def finalization_reserve(self) -> int:
        return self.policy.finalization_reserve if self.policy else 0

    def snapshot(self) -> dict[str, object]:
        return {
            "base_budget": self.policy.base_budget if self.policy else self.max_total_tokens,
            "used": self.total_tokens, "soft_limit": self.max_total_tokens,
            "hard_limit": self.hard_limit, "finalization_reserve": self.finalization_reserve,
            "extension_count": self.extension_count, "extensions": list(self.extension_history),
            "stage_usage": dict(self.stage_usage), "model_calls": self.calls,
            "context_reports": list(self.context_reports),
        }

    def request_extension(self, request: BudgetExtensionRequest) -> dict[str, object]:
        index = self.extension_count + 1
        self._emit("budget_extension_requested", "info", "已申请额外预算",
                   {"extension_index": index, "stage": request.stage,
                    "reason_code": "requested", "used_before": self.total_tokens,
                    "requested_extra": request.estimated_extra_tokens,
                    "approved_extra": 0, "hard_limit": self.hard_limit})
        limit = (self.policy.extension_1_limit if index == 1 else
                 self.policy.extension_2_limit if self.policy and index == 2 else 0) if self.policy else 0
        evidence = request.progress_evidence
        progress = bool(evidence.get("completed_actions") or evidence.get("last_success_step")
                        or evidence.get("state_changed") or evidence.get("new_result"))
        reason_code = "approved"
        if self.policy is None or index > 2 or limit <= 0:
            reason_code = "extension_limit"
        elif self.total_tokens < (self.max_total_tokens - self.finalization_reserve) * self.policy.warning_ratio:
            reason_code = "not_needed"
        elif self.total_tokens >= self.hard_limit or self.max_total_tokens >= self.hard_limit:
            reason_code = "hard_limit"
        elif request.remaining_actions == 0 and request.stage not in {"recovery", "finalization"}:
            reason_code = "no_remaining_action"
        elif evidence.get("remaining_actions_verified") is False:
            reason_code = "remaining_actions_mismatch"
        elif request.stage in {"recovery", "finalization"} and not progress:
            reason_code = "no_completed_action"
        elif not progress:
            reason_code = "no_progress"
        elif int(evidence.get("repeated_error_count") or 0) >= 2 or int(evidence.get("stalled_rounds") or 0) >= 2:
            reason_code = "repeated_failure"
        elif index == 2 and (request.stage not in {"recovery", "finalization", "tool_execution"}
                             or request.remaining_actions > 1):
            reason_code = "second_extension_restricted"
        elif index == 2 and request.stage == "tool_execution" and not evidence.get("corrective_retry"):
            reason_code = "second_extension_restricted"
        elif request.estimated_extra_tokens > limit * 2:
            reason_code = "excessive_request"
        approved = min(request.estimated_extra_tokens, limit, self.hard_limit - self.max_total_tokens) if reason_code == "approved" else 0
        if reason_code == "approved" and approved <= 0:
            reason_code = "hard_limit"
        if approved:
            self.max_total_tokens += approved
            self.extension_count += 1
        outcome = {
            "extension_index": index, "stage": request.stage, "reason_code": reason_code,
            "used_before": self.total_tokens, "requested_extra": request.estimated_extra_tokens,
            "approved_extra": approved, "hard_limit": self.hard_limit,
        }
        self.extension_history.append(outcome)
        self._emit("budget_extension_approved" if approved else "budget_extension_rejected",
                   "success" if approved else "warning",
                   "额外预算已批准" if approved else "额外预算申请未通过", outcome)
        return outcome

    @staticmethod
    def _emit(event_type: str, outcome: str, label: str, metadata: dict[str, object]) -> None:
        from zhaoxi.observability import current_trace
        trace = current_trace()
        budget_logger.info("trace_id=%s request_id=%s step=%s stage=budget event=%s %s",
                           trace.trace_id if trace else None,
                           trace.request_id if trace else None,
                           trace.current_step if trace else None, event_type,
                           " ".join(f"{key}={value}" for key, value in metadata.items()))
        if trace:
            trace.emit(event_type, "token_budget", outcome, label,
                       step_id=trace.current_step, metadata=metadata)

    def consume(self) -> None:
        if self.calls >= self.max_calls:
            raise ProviderError(
                "本次任务的模型调用预算已用完。",
                code="provider_call_budget_exhausted",
                retryable=False,
            )
        stage = current_budget_stage()
        if self.total_tokens >= self.hard_limit:
            raise ProviderError("本次任务的 Token 绝对上限已用完。",
                                code="provider_token_budget_exhausted", retryable=False)
        if self.policy and self.total_tokens >= self.max_total_tokens - (
                0 if stage in {"finalization", "recovery"} else self.finalization_reserve):
            raise ProviderError("本次任务需要受控扩容或进入收尾阶段。",
                                code="provider_soft_budget_exhausted", retryable=False)
        if self.policy and stage in {"finalization", "recovery"} and not self.reserve_entered \
                and self.total_tokens >= self.max_total_tokens - self.finalization_reserve:
            self.reserve_entered = True
            self._emit("finalization_reserve_entered", "info", "正在使用收尾预算",
                       {"used_before": self.total_tokens, "reserve": self.finalization_reserve,
                        "soft_limit": self.max_total_tokens, "hard_limit": self.hard_limit})
        self.calls += 1

    def record_tokens(self, tokens: int, *, input_tokens: int | None = None,
                      output_tokens: int | None = None, provider: str | None = None,
                      model: str | None = None) -> None:
        used_before = self.total_tokens
        self.total_tokens += max(0, tokens)
        stage = current_budget_stage()
        self.stage_usage[stage] = self.stage_usage.get(stage, 0) + max(0, tokens)
        if self.context_reports and self.context_reports[-1].get("actual_input_tokens") is None:
            self.context_reports[-1]["actual_input_tokens"] = input_tokens
            self.context_reports[-1]["total_input_tokens"] = input_tokens
        from zhaoxi.observability import current_trace
        trace = current_trace()
        fields = {
            "used_before": used_before, "call_input_tokens": input_tokens,
            "call_output_tokens": output_tokens, "call_total": tokens,
            "used_after": self.total_tokens, "limit": self.max_total_tokens,
            "step": trace.current_step if trace else None,
            "provider": provider, "model": model,
        }
        if self.policy:
            fields.update(hard_limit=self.hard_limit, stage=stage)
        warning_ratio = self.policy.warning_ratio if self.policy else 0.9
        if self.total_tokens >= self.max_total_tokens * warning_ratio:
            event_type = "token_budget_exhausted" if self.total_tokens > self.hard_limit else "token_budget_warning"
            budget_logger.warning("stage=token_budget event=%s %s", event_type,
                                  " ".join(f"{key}={value}" for key, value in fields.items()))
            if trace:
                trace.emit(event_type, "token_budget",
                           "failed" if event_type == "token_budget_exhausted" else "warning",
                           "本次请求 Token 预算已耗尽" if event_type == "token_budget_exhausted" else "本次请求接近 Token 预算上限",
                           step_id=trace.current_step,
                           error_code="token_budget_exhausted" if event_type == "token_budget_exhausted" else None,
                           metadata=fields)
        if self.total_tokens > self.hard_limit:
            raise ProviderError(
                "本次任务的 Token 预算已用完。",
                code="provider_token_budget_exhausted",
                retryable=False,
            )


_budget: ContextVar[CallBudget | None] = ContextVar("zhaoxi_provider_budget", default=None)
_stage: ContextVar[str] = ContextVar("zhaoxi_budget_stage", default="planning")


def current_budget() -> CallBudget | None:
    return _budget.get()


def current_budget_stage() -> str:
    return _stage.get()


@contextmanager
def budget_stage_scope(stage: str):
    token = _stage.set(stage)
    try:
        yield
    finally:
        _stage.reset(token)


@contextmanager
def provider_budget_scope(max_calls: int, max_total_tokens: int = 100_000,
                          *, policy: BudgetPolicy | None = None):
    token = _budget.set(CallBudget(max_calls=max_calls,
                                  max_total_tokens=policy.base_budget if policy else max_total_tokens,
                                  policy=policy))
    try:
        yield _budget.get()
    finally:
        _budget.reset(token)


def consume_provider_budget() -> None:
    budget = _budget.get()
    if budget is not None:
        budget.consume()


def record_provider_tokens(tokens: int, *, input_tokens: int | None = None,
                           output_tokens: int | None = None, provider: str | None = None,
                           model: str | None = None) -> None:
    budget = _budget.get()
    if budget is not None:
        budget.record_tokens(tokens, input_tokens=input_tokens, output_tokens=output_tokens,
                             provider=provider, model=model)


def record_context_diagnostics(report: dict[str, object]) -> None:
    budget = current_budget()
    if budget is None:
        return
    from zhaoxi.observability import current_trace
    trace = current_trace()
    entry = {"step": trace.current_step if trace else None,
             "stage": current_budget_stage(),
             "estimated": report.get("context_tokens_estimate", {}),
             "actual_input_tokens": None, "total_input_tokens": None}
    budget.context_reports.append(entry)
    budget.context_reports[:] = budget.context_reports[-30:]
    if trace:
        trace.emit("context_measured", "context", "info", "已测量本轮上下文",
                   step_id=trace.current_step, metadata=entry)


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
