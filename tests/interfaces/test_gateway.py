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
from zhaoxi.reliability import current_correlation


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


class CorrelationAgent(FakeAgent):
    async def run_natural(self, content: str):
        context = current_correlation()
        assert context is not None
        assert context.request_id == "correlated-request"
        assert context.session_id == "session-1"
        return await super().run_natural(content)


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


async def test_gateway_records_metrics_and_propagates_correlation():
    gateway = InterfaceGateway(CorrelationAgent())
    message = UnifiedMessage(
        request_id="correlated-request",
        session_id="session-1",
        channel="web",
        content="你好",
    )

    await gateway.chat(message)
    await gateway.chat(message)

    snapshot = gateway.metrics.snapshot()
    assert snapshot["counters"] == {
        "interface.chat.cache_hit": 1,
        "interface.chat.completed": 1,
        "interface.chat.started": 1,
    }
    assert snapshot["durations"]["interface.chat"]["count"] == 1

async def test_merged_request_keeps_display_parts_after_message_roundtrip():
    from zhaoxi.core.message import Message
    from zhaoxi.interfaces.models import DisplayPart
    agent = FakeAgent()
    gateway = InterfaceGateway(agent)
    parts = [DisplayPart(text='first', timestamp='2026-09-09T06:00:00Z'),
             DisplayPart(text='second', timestamp='2026-09-09T06:00:02Z')]
    await gateway.chat(UnifiedMessage(channel=InterfaceChannel.WEB, content='first\n\nsecond', display_parts=parts))
    assert agent.calls == 1
    assert agent.conversation.messages[0].content == 'first\n\nsecond'
    agent.conversation = Conversation([Message.model_validate_json(m.model_dump_json()) for m in agent.conversation.messages])
    assert gateway.session()[0]['display_parts'] == [p.model_dump(mode='json') for p in parts]
