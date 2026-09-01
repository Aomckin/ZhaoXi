import asyncio
from types import SimpleNamespace

from zhaoxi.core.agent import AgentResponse
from zhaoxi.core.conversation import Conversation
from zhaoxi.interfaces import InterfaceChannel, InterfaceGateway, UnifiedMessage


class SoakAgent:
    def __init__(self):
        self.conversation = Conversation(max_messages=20)
        self.provider = SimpleNamespace(max_calls=2)
        self.tool_executor = SimpleNamespace(
            gateway=SimpleNamespace(store=SimpleNamespace(pending={}))
        )
        self._pending_permissions = {}
        self.planner = None
        self.workflow = None

    async def run_natural(self, content):
        await asyncio.sleep(0)
        self.conversation.add_user(content)
        self.conversation.add_assistant("ok")
        return AgentResponse(content="ok", request_id=f"core-{content}", steps=1)


async def test_accelerated_gateway_soak_stays_bounded():
    agent = SoakAgent()
    gateway = InterfaceGateway(agent, response_cache_size=25)

    for batch in range(20):
        messages = [
            UnifiedMessage(
                request_id=f"{batch}-{index}",
                channel=InterfaceChannel.WEB,
                content=f"message-{batch}-{index}",
            )
            for index in range(25)
        ]
        await asyncio.gather(*(gateway.chat(message) for message in messages))

    snapshot = gateway.metrics.snapshot()
    assert snapshot["counters"]["interface.chat.completed"] == 500
    assert snapshot["durations"]["interface.chat"]["count"] == 500
    assert len(gateway._responses) == 25
    assert len(agent.conversation.messages) == 20
