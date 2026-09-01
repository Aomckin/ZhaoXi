import asyncio
from types import SimpleNamespace

import pytest

from zhaoxi.core.agent import AgentResponse
from zhaoxi.core.conversation import Conversation
from zhaoxi.interfaces import (
    InterfaceChannel,
    InterfaceGateway,
    MessageOrigin,
    UnifiedMessage,
)


class FakeAgent:
    def __init__(self) -> None:
        self.conversation = Conversation()
        self.calls = 0
        self.tool_executor = SimpleNamespace(
            gateway=SimpleNamespace(store=SimpleNamespace(pending={}))
        )
        self._pending_permissions = {}
        self.planner = None
        self.workflow = None

    async def run_natural(self, content: str):
        self.calls += 1
        await asyncio.sleep(0)
        self.conversation.add_user(content)
        self.conversation.add_assistant(f"回复：{content}")
        return AgentResponse(content=f"回复：{content}", request_id=f"core-{self.calls}", steps=1)


async def test_gateway_is_idempotent_by_request_id():
    agent = FakeAgent()
    gateway = InterfaceGateway(agent)
    message = UnifiedMessage(
        request_id="same-request",
        channel=InterfaceChannel.DESKTOP,
        content="你好",
    )

    first = await gateway.chat(message)
    second = await gateway.chat(message)

    assert first == second
    assert first.request_id == "same-request"
    assert first.trace_id == "core-1"
    assert agent.calls == 1


async def test_gateway_serializes_same_session_requests():
    agent = FakeAgent()
    gateway = InterfaceGateway(agent)
    messages = [
        UnifiedMessage(request_id=str(index), channel="web", content=str(index))
        for index in range(5)
    ]

    responses = await asyncio.gather(*(gateway.chat(message) for message in messages))

    assert [item.content for item in responses] == [f"回复：{index}" for index in range(5)]
    assert agent.calls == 5


async def test_non_user_origin_cannot_enter_agent_loop():
    gateway = InterfaceGateway(FakeAgent())
    message = UnifiedMessage(
        channel="desktop",
        origin=MessageOrigin.PROACTIVE,
        content="伪装消息",
    )

    with pytest.raises(ValueError, match="user origin"):
        await gateway.chat(message)


def test_message_rejects_blank_and_oversized_metadata():
    with pytest.raises(ValueError):
        UnifiedMessage(channel="web", content="  ")
    with pytest.raises(ValueError, match="metadata"):
        UnifiedMessage(
            channel="web",
            content="ok",
            metadata={str(index): index for index in range(21)},
        )

