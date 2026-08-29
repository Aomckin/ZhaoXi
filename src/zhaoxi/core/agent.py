"""The minimal extensible Zhaoxi agent loop."""

import asyncio
import json
import logging
from dataclasses import dataclass
from uuid import uuid4

from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.errors import AgentLoopError, ProviderError, ToolNotFoundError
from zhaoxi.models.base import ModelProvider
from zhaoxi.memory.models import MemorySearchResult
from zhaoxi.tools.base import ToolResult
from zhaoxi.tools.registry import ToolRegistry

logger = logging.getLogger("AGENT")
tool_logger = logging.getLogger("TOOL")
model_logger = logging.getLogger("MODEL")


@dataclass(slots=True)
class AgentResponse:
    """Final user-facing response plus trace metadata."""

    content: str
    request_id: str
    steps: int


class ZhaoxiAgent:
    """Run model/tool iterations without knowing any concrete provider or tool."""

    def __init__(
        self,
        *,
        provider: ModelProvider,
        registry: ToolRegistry,
        context_builder: ContextBuilder,
        conversation: Conversation | None = None,
        max_steps: int = 8,
        timeout_seconds: float = 60,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.context_builder = context_builder
        self.conversation = conversation or Conversation()
        self.max_steps = max_steps
        self.timeout_seconds = timeout_seconds

    async def run(self, user_message: str) -> AgentResponse:
        """Accept one user turn and return a final natural-language response."""
        if not user_message.strip():
            raise ValueError("消息不能为空。")
        request_id = uuid4().hex
        self.conversation.add_user(user_message.strip())
        logger.info("request=%s received user input", request_id)
        memories = []
        if self.context_builder.memory_retriever:
            try:
                memories = await self.context_builder.memory_retriever.retrieve(user_message.strip())
                logger.info("request=%s memory_hits=%d", request_id, len(memories))
            except Exception:
                logger.exception("request=%s memory retrieval failed; continuing without memory", request_id)
        try:
            return await asyncio.wait_for(
                self._run_loop(request_id, memories), timeout=self.timeout_seconds
            )
        except TimeoutError as exc:
            logger.error("request=%s timed out", request_id)
            raise AgentLoopError(f"请求超过 {self.timeout_seconds:g} 秒，已停止。") from exc

    async def _run_loop(
        self, request_id: str, memories: list[MemorySearchResult] | None = None
    ) -> AgentResponse:
        schemas = self.registry.schemas()
        for step in range(1, self.max_steps + 1):
            model_logger.info("request=%s step=%d calling model", request_id, step)
            try:
                response = await self.provider.generate(
                    self.context_builder.build(self.conversation, memories), schemas
                )
            except ProviderError:
                logger.exception("request=%s provider error", request_id)
                raise

            if not response.tool_calls:
                content = response.content or "模型没有返回可显示的内容。"
                self.conversation.add_assistant(content)
                logger.info("request=%s final response step=%d", request_id, step)
                return AgentResponse(content=content, request_id=request_id, steps=step)

            self.conversation.add_assistant(response.content, tool_calls=response.tool_calls)
            for call in response.tool_calls:
                tool_logger.info("request=%s tool=%s arguments=%s", request_id, call.name, call.arguments)
                result = await self._execute_tool(call.name, call.arguments)
                self.conversation.add_tool(
                    json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
                    tool_call_id=call.id,
                    name=call.name,
                )
                tool_logger.info("request=%s tool=%s success=%s", request_id, call.name, result.success)

        logger.error("request=%s reached max steps=%d", request_id, self.max_steps)
        raise AgentLoopError(f"已达到最大执行步数（{self.max_steps}），为避免无限循环已停止。")

    async def _execute_tool(self, name: str, arguments: dict[str, object]) -> ToolResult:
        try:
            tool = self.registry.get(name)
        except ToolNotFoundError as exc:
            return ToolResult(success=False, content="请求的工具不存在。", error=str(exc))
        return await tool.run(arguments)
