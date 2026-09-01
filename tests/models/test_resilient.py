import pytest

from zhaoxi.core.message import Message, Role
from zhaoxi.errors import ProviderError
from zhaoxi.models.base import ModelProvider
from zhaoxi.models.resilient import ResilientProvider
from zhaoxi.models.types import ModelResponse
from zhaoxi.reliability.retry import RetryPolicy, provider_budget_scope


class FakeProvider(ModelProvider):
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def generate(self, messages, tools=None, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return ModelResponse(content=outcome)


@pytest.mark.asyncio
async def test_resilient_provider_retries_then_falls_back():
    primary = FakeProvider([
        ProviderError("503", retryable=True),
        ProviderError("503", retryable=True),
    ])
    fallback = FakeProvider(["fallback ok"])

    async def no_sleep(_):
        pass

    provider = ResilientProvider(
        [primary, fallback],
        retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=0),
        sleeper=no_sleep,
    )
    with provider_budget_scope(3):
        response = await provider.generate([Message(role=Role.USER, content="hi")])
    assert response.content == "fallback ok"
    assert primary.calls == 2
    assert fallback.calls == 1


@pytest.mark.asyncio
async def test_resilient_provider_does_not_fallback_on_auth_error():
    primary = FakeProvider([ProviderError("401", code="provider_http_401")])
    fallback = FakeProvider(["must not run"])
    provider = ResilientProvider([primary, fallback])
    with pytest.raises(ProviderError, match="401"):
        await provider.generate([Message(role=Role.USER, content="hi")])
    assert fallback.calls == 0
