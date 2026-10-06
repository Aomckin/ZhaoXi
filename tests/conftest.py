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
        self.tool_schemas: list[list[dict[str, Any]] | None] = []
        self.options: list[dict[str, Any]] = []

    async def generate(
        self, messages: Sequence[Message], tools: list[dict[str, Any]] | None = None, **kwargs: Any
    ) -> ModelResponse:
        self.calls.append(list(messages))
        self.tool_schemas.append(tools)
        self.options.append(dict(kwargs))
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


@pytest.fixture(scope="session")
def five_large_photos():
    """Five distinct synthetic 2-3 MB photos; no user files or external service."""
    import base64
    import random
    from io import BytesIO
    from PIL import Image, ImageDraw
    source = Image.frombytes("RGB", (2000, 1600), random.Random(42).randbytes(2000 * 1600 * 3))
    photos = []
    for index in range(5):
        frame = source.copy()
        ImageDraw.Draw(frame).rectangle((0, 0, 100, 100), fill=(30 + index * 40, 80, 100))
        output = BytesIO()
        frame.save(output, format="JPEG", quality=90)
        photos.append("data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode("ascii"))
    return tuple(photos)
