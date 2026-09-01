import asyncio

import pytest

from zhaoxi.reliability import (
    CorrelationContext,
    ErrorCategory,
    MetricRegistry,
    ReliabilityError,
    correlation_scope,
    current_correlation,
)


def test_reliability_error_enforces_retry_contract_and_safe_summary():
    error = ReliabilityError(
        "服务暂时不可用",
        code="provider_unavailable",
        category=ErrorCategory.TRANSIENT,
        retryable=True,
        safe_to_replay=True,
        trace_id="trace-1",
        cause_type="ConnectError",
    )

    assert str(error) == "服务暂时不可用"
    assert error.safe_summary() == {
        "code": "provider_unavailable",
        "category": "transient",
        "retryable": True,
        "safe_to_replay": True,
        "trace_id": "trace-1",
        "cause_type": "ConnectError",
    }
    with pytest.raises(ValueError, match="transient"):
        ReliabilityError(
            "配置无效",
            code="bad_config",
            category=ErrorCategory.VALIDATION,
            retryable=True,
        )


async def test_correlation_context_is_isolated_between_async_tasks():
    async def read(trace_id: str):
        with correlation_scope(CorrelationContext(trace_id=trace_id)):
            await asyncio.sleep(0)
            return current_correlation().trace_id

    assert await asyncio.gather(read("a"), read("b")) == ["a", "b"]
    assert current_correlation() is None


def test_metric_registry_returns_bounded_aggregates():
    metrics = MetricRegistry()
    metrics.increment("interface.chat.started")
    metrics.observe_duration("interface.chat", 0.25)
    metrics.observe_duration("interface.chat", 0.75)

    snapshot = metrics.snapshot()
    assert snapshot["counters"] == {"interface.chat.started": 1}
    assert snapshot["durations"]["interface.chat"] == {
        "count": 2,
        "total_seconds": 1.0,
        "average_seconds": 0.5,
    }
    with pytest.raises(ValueError, match="metric name"):
        metrics.increment("user supplied label")
