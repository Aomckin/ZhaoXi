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
from zhaoxi.models.types import ToolCall
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


async def test_current_cognition_maintenance_runs_after_reply_and_is_nonfatal():
    agent = FakeAgent()
    seen = []

    class Maintainer:
        async def maintain(self, messages, **_kwargs):
            seen.append([(item.role.value, item.content) for item in messages])
            raise RuntimeError("maintenance unavailable")

    agent.current_cognition_maintainer = Maintainer()
    gateway = InterfaceGateway(agent)
    response = await gateway.chat(UnifiedMessage(
        request_id="cognition-post-turn", channel=InterfaceChannel.WEB, content="你好"))
    assert response.content == "回复：你好"
    assert seen == [[("user", "你好"), ("assistant", "回复：你好")]]


async def test_current_cognition_bootstrap_uses_existing_history_once():
    agent = FakeAgent()
    agent.conversation.add_user("旧会话里的秋招讨论")
    agent.conversation.add_assistant("先继续准备")
    seen = []

    class State:
        last_processed_message_id = None

    class Maintainer:
        service = SimpleNamespace(state=lambda: State())

        async def maintain(self, messages, **_kwargs):
            seen.append([item.content for item in messages])

    agent.current_cognition_maintainer = Maintainer()
    gateway = InterfaceGateway(agent)
    await gateway.chat(UnifiedMessage(request_id="bootstrap", channel=InterfaceChannel.WEB, content="新消息"))
    assert seen[0] == ["旧会话里的秋招讨论", "先继续准备"]
    assert seen[1][-2:] == ["新消息", "回复：新消息"]


class CorrelationAgent(FakeAgent):
    async def run_natural(self, content: str):
        context = current_correlation()
        assert context is not None
        assert context.request_id == "correlated-request"
        assert context.session_id == "session-1"
        return await super().run_natural(content)


class InterruptedToolAgent(FakeAgent):
    def __init__(self) -> None:
        super().__init__()
        self.resumed = 0

    async def resume_current_turn(self, content: str):
        self.resumed += 1
        assert [item.role.value for item in self.conversation.messages] == [
            "user", "assistant", "tool"
        ]
        self.conversation.add_assistant(f"续写：{content}")
        return AgentResponse(content=f"续写：{content}", request_id="core-resumed", steps=1)


class MultipleEmojiAgent(FakeAgent):
    async def run_natural(self, content: str):
        self.calls += 1
        self.conversation.add_user(content)
        for emoji_id in ("emoji_a", "emoji_b", "emoji_c"):
            self.conversation.add_assistant_image(
                f"/api/expression/emoji/{emoji_id}", source="emoji", emoji_id=emoji_id
            )
        self.conversation.add_assistant("三张都已通过真实消息发送。")
        return AgentResponse(content="三张都已通过真实消息发送。", request_id="multi", steps=2)


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
    assert first.trace_id == "same-request"
    assert first.activity["core_request_id"] == "core-1"
    assert first.message_id == agent.conversation.messages[-1].message_id
    assert agent.calls == 1


async def test_live_and_history_share_ordered_multiple_image_contract():
    gateway = InterfaceGateway(MultipleEmojiAgent())
    response = await gateway.chat(UnifiedMessage(
        request_id="multi-request", channel=InterfaceChannel.WEB, content="发送多张"
    ))

    images = [item for item in response.output_messages if item["type"] == "image"]
    assert [item["emoji_id"] for item in images] == ["emoji_a", "emoji_b", "emoji_c"]
    assert all(item["text"] == "" and item["source"] == "emoji" for item in images)
    history_images = [item for item in gateway.session() if item["type"] == "image"]
    assert history_images == images


async def test_regenerate_replaces_latest_reply_without_duplicating_user_turn():
    agent = FakeAgent()
    gateway = InterfaceGateway(agent)
    original = await gateway.chat(UnifiedMessage(
        request_id="first", channel=InterfaceChannel.WEB, content="再试一次"
    ))
    user = agent.conversation.messages[0].model_copy(deep=True)

    regenerated = await gateway.regenerate(original.message_id, request_id="retry")

    assert regenerated.request_id == "retry"
    assert regenerated.message_id != original.message_id
    assert [item.role.value for item in agent.conversation.messages] == ["user", "assistant"]
    assert agent.conversation.messages[0].message_id == user.message_id
    assert agent.conversation.messages[0].timestamp == user.timestamp
    assert agent.calls == 2
    session = gateway.session()
    assert session[-1]["message_id"] == regenerated.message_id
    assert session[-1]["regeneratable"] is True
    assert session[0]["regeneratable"] is False


async def test_regenerate_updates_matching_emoji_trace():
    agent = FakeAgent()
    gateway = InterfaceGateway(agent)
    original = await gateway.chat(UnifiedMessage(
        request_id="first", channel=InterfaceChannel.WEB, content="再试一次"
    ))
    agent.last_emoji_trace = {
        "trace_id": "retry",
        "message_ids": [original.message_id],
    }

    await gateway.regenerate(original.message_id, request_id="retry")

    assert agent.last_emoji_trace["persisted"] is False
    assert agent.last_emoji_trace["gateway_emitted"] is False


async def test_regenerate_rejects_an_older_reply_and_keeps_history():
    agent = FakeAgent()
    gateway = InterfaceGateway(agent)
    first = await gateway.chat(UnifiedMessage(channel="web", content="第一条"))
    await gateway.chat(UnifiedMessage(channel="web", content="第二条"))
    before = [item.message_id for item in agent.conversation.messages]

    with pytest.raises(ValueError, match="最后一条"):
        await gateway.regenerate(first.message_id, request_id="retry-old")

    assert [item.message_id for item in agent.conversation.messages] == before


async def test_regenerate_can_retry_latest_unanswered_user_after_provider_failure():
    agent = FakeAgent()
    unanswered = agent.conversation.add_user("刚才没回出来")
    gateway = InterfaceGateway(agent)

    regenerated = await gateway.regenerate(unanswered.message_id, request_id="retry-user")

    assert regenerated.content == "回复：刚才没回出来"
    assert [item.role.value for item in agent.conversation.messages] == ["user", "assistant"]
    assert agent.conversation.messages[0].message_id == unanswered.message_id


async def test_regenerate_resumes_after_completed_tool_without_replaying_it():
    agent = InterruptedToolAgent()
    user = agent.conversation.add_user("记住这个")
    interrupted = agent.conversation.add_assistant(
        "",
        tool_calls=[ToolCall(id="call-1", name="remember_memory", arguments={"content": "x"})],
    )
    agent.conversation.add_tool(
        '{"success":true}', tool_call_id="call-1", name="remember_memory"
    )
    gateway = InterfaceGateway(agent)

    regenerated = await gateway.regenerate(interrupted.message_id, request_id="resume-tool")

    assert regenerated.content == "续写：记住这个"
    assert agent.resumed == 1
    assert agent.conversation.messages[0].message_id == user.message_id
    assert [item.role.value for item in agent.conversation.messages] == [
        "user", "assistant", "tool", "assistant"
    ]


async def test_failed_regenerate_restores_original_conversation():
    agent = FakeAgent()
    gateway = InterfaceGateway(agent)
    original = await gateway.chat(UnifiedMessage(channel="web", content="原问题"))
    before = [(item.message_id, item.content) for item in agent.conversation.messages]

    async def fail(_content):
        raise RuntimeError("offline")

    agent.run_natural = fail

    with pytest.raises(RuntimeError, match="offline"):
        await gateway.regenerate(original.message_id, request_id="retry-failed")

    assert [(item.message_id, item.content) for item in agent.conversation.messages] == before


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

async def test_existing_task_notice_reclassified_without_duplicate():
    from zhaoxi.proactive.models import Delivery, Priority
    from zhaoxi.core.message import Message, Role
    agent=FakeAgent()
    gateway=InterfaceGateway(agent)
    delivery=Delivery(event_id='task',subscription_id='tidal',event_type='task.completed',priority=Priority.INFO,content='Task completed',decision_reason='inbox')
    agent.conversation.add(Message(role=Role.ASSISTANT,content=delivery.content,delivery_id=delivery.delivery_id))
    gateway._include_delivery(delivery)
    assert len(agent.conversation.messages)==1
    assert gateway.session()[0]['kind']=='system'
    assert delivery.model_dump()['kind']=='system'
    beat=delivery.model_copy(update={'event_type':'conversation.beat','decision_reason':'active_conversation_beat'})
    assert beat.kind=='assistant'
