import asyncio

import pytest

from zhaoxi.sdk.retry import RetryPolicy as SDKRetryPolicy, retry_async as sdk_retry_async

from zhaoxi.errors import ProviderError
from zhaoxi.reliability.retry import RetryPolicy, provider_budget_scope, retry_async


@pytest.mark.asyncio
@pytest.mark.parametrize("policy_type", [RetryPolicy, SDKRetryPolicy])
async def test_retry_is_bounded_and_uses_injected_sleeper(policy_type):
    attempts = 0
    delays = []

    async def operation():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ProviderError("temporary", retryable=True)
        return "ok"

    async def sleeper(delay):
        delays.append(delay)

    result = await retry_async(
        operation,
        policy=policy_type(max_attempts=3, base_delay_seconds=1, jitter_ratio=0),
        should_retry=lambda exc: isinstance(exc, ProviderError) and exc.retryable,
        sleeper=sleeper,
    )
    assert result == "ok"
    assert attempts == 3
    assert delays == [1, 2]


@pytest.mark.asyncio
async def test_retry_does_not_repeat_permanent_failure():
    attempts = 0

    async def operation():
        nonlocal attempts
        attempts += 1
        raise ProviderError("bad auth", code="provider_http_401")

    with pytest.raises(ProviderError):
        await retry_async(
            operation,
            policy=RetryPolicy(),
            should_retry=lambda exc: isinstance(exc, ProviderError) and exc.retryable,
        )
    assert attempts == 1


def test_provider_budget_has_hard_limit():
    from zhaoxi.reliability.retry import consume_provider_budget, record_provider_tokens

    with provider_budget_scope(2):
        consume_provider_budget()
        consume_provider_budget()
        with pytest.raises(ProviderError, match="预算"):
            consume_provider_budget()

    with provider_budget_scope(2, 10):
        record_provider_tokens(6)
        with pytest.raises(ProviderError, match="Token"):
            record_provider_tokens(5)


@pytest.mark.parametrize("policy_type", [RetryPolicy, SDKRetryPolicy])
def test_retry_jitter_and_policy_validation(policy_type):
    policy = policy_type(base_delay_seconds=2, max_delay_seconds=3, jitter_ratio=0.5)
    assert policy.delay(1, random_value=0) == 1
    assert policy.delay(1, random_value=1) == 3
    assert policy.delay(3, random_value=0.5) == 3
    with pytest.raises(ValueError, match="jitter_ratio"):
        policy_type(jitter_ratio=1.1)
    assert SDKRetryPolicy().jitter_ratio == 0
    assert RetryPolicy().jitter_ratio == 0.1
    assert retry_async is sdk_retry_async


@pytest.mark.parametrize("policy_type", [RetryPolicy, SDKRetryPolicy])
async def test_retry_preserves_cancellation(policy_type):
    attempts = 0

    async def operation():
        nonlocal attempts
        attempts += 1
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await retry_async(operation, policy=policy_type(), should_retry=lambda exc: True)
    assert attempts == 1
