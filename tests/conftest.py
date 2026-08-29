import asyncio
import inspect
from collections import deque
from typing import Any, Sequence

import pytest

from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.core.message import Message
from zhaoxi.models.base import ModelProvider
from zhaoxi.models.types import ModelResponse
from zhaoxi.tools.builtin import create_builtin_tools
from zhaoxi.tools.registry import ToolRegistry


def pytest_pyfunc_call(pyfuncitem):
    """Run coroutine tests without requiring an async pytest plugin."""
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        arguments = {name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames}
        asyncio.run(pyfuncitem.obj(**arguments))
        return True
    return None


class FakeProvider(ModelProvider):
    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = deque(responses)
        self.calls: list[list[Message]] = []

    async def generate(
        self, messages: Sequence[Message], tools: list[dict[str, Any]] | None = None, **kwargs: Any
    ) -> ModelResponse:
        self.calls.append(list(messages))
        if len(self.responses) == 1:
            return self.responses[0]
        return self.responses.popleft()


@pytest.fixture
def registry() -> ToolRegistry:
    value = ToolRegistry()
    for tool in create_builtin_tools():
        value.register(tool)
    return value


@pytest.fixture
def context_builder() -> ContextBuilder:
    return ContextBuilder("你是朝汐。")


@pytest.fixture
def conversation() -> Conversation:
    return Conversation()
