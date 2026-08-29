"""Model provider abstraction."""

from abc import ABC, abstractmethod
from typing import Any, Sequence

from zhaoxi.core.message import Message
from zhaoxi.models.types import ModelResponse


class ModelProvider(ABC):
    """Provider-neutral asynchronous model interface."""

    @abstractmethod
    async def generate(
        self,
        messages: Sequence[Message],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Generate text or tool calls from a conversation context."""

