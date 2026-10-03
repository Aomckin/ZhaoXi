"""FAST expression admission, persistence and QQ transport regression checks."""
import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from conftest import FakeProvider
from test_reply_dsl import make_service
from zhaoxi.cognitive.coordinator import CognitiveCoordinator
from zhaoxi.cognitive.fast_gate import FastDialogueGate, FastGateLane
from zhaoxi.cognitive.router import CognitiveRouter
from zhaoxi.cognitive_stream import AttentionRetriever, CognitiveIngress, ExperienceStream
from zhaoxi.cognitive_stream.models import CognitiveEventType
from zhaoxi.config.settings import Settings
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.fast_chat import FastEscalationKind
from zhaoxi.core.reply import ResolvedReply
from zhaoxi.interfaces import InterfaceChannel, InterfaceGateway, UnifiedMessage
from zhaoxi.models.types import ModelResponse
from zhaoxi.perception.models import Observation
from zhaoxi.perception.runtime import PerceptionRuntime
from zhaoxi.plugins.source_router import PerceptionSink, outbound_message
from zhaoxi.reliability import MetricRegistry
from zhaoxi.sdk.external_source import SendResult
from zhaoxi.session.base import Session
from zhaoxi.session.sqlite import SQLiteSessionStore
from zhaoxi.tools.registry import ToolRegistry
from zhaoxi_ext.qq_napcat.config import QQConfig
from zhaoxi_ext.qq_napcat.outbound import send_reply


def make_agent(tmp_path, replies):
    service = make_service(tmp_path)
    provider = FakeProvider([ModelResponse(content=reply) for reply in replies])
    agent = ZhaoxiAgent(provider=provider, registry=ToolRegistry(override_path=tmp_path / "tools.json"),
                        context_builder=ContextBuilder("朝汐", emoji_service=service))
    agent.cognitive = CognitiveCoordinator(agent=agent, router=CognitiveRouter(provider),
                                            fast_gate=FastDialogueGate())
    agent.session_store = SQLiteSessionStore(tmp_path / "sessions.db")
    return agent, provider, service


def make_perception(tmp_path, replies):
    agent, provider, service = make_agent(tmp_path, replies)
    agent.metrics = MetricRegistry()
    agent.conversation_lock = asyncio.Lock()
    agent.experience_stream = ExperienceStream(tmp_path / "events.db")
    agent.cognitive_ingress = CognitiveIngress(agent.experience_stream)
    agent.attention_retriever = AttentionRetriever(agent.experience_stream)
    agent.context_builder.attention_retriever = agent.attention_retriever
    settings = Settings(_env_file=None, perception_db_path=str(tmp_path / "perception.db"),
                        session_db_path=str(tmp_path / "sessions.db"),
                        media_directory=str(tmp_path / "media"),
                        perception_image_temp_dir=str(tmp_path / "images"))
    runtime = PerceptionRuntime(settings, agent)
    return runtime, agent, provider, service


def observation(message_id="1"):
    return Observation(source="qq", source_plugin="qq_napcat", source_kind="message",
                       actor_role="OWNER", actor_id="8", conversation_kind="private",
                       conversation_id="8", content="发个得意表情", raw_ref="qq:private:8:" + message_id,
                       metadata={"message_id": message_id})


@pytest.mark.parametrize("text", ["发个得意表情", "请发一个表情给我", "用开心表情回复我", "来个表情包吧"])
def test_reply_expression_enters_fast_without_tool_authorization(text):
    assert FastDialogueGate().decide(text, capability_groups=["emoji"]).lane is FastGateLane.FAST_CONFIDENT
    assert not FastDialogueGate().decide(text, images=["image"]).eligible
    assert not FastDialogueGate().decide(text, pending_permission=True).eligible
    from zhaoxi.core.fast_chat import FastChatRuntime
    assert not FastChatRuntime.current_evidence(text, FastEscalationKind.TOOL)


@pytest.mark.parametrize("text", ["保存这个表情包", "请收藏这个表情", "发送并保存表情", "给群友发送表情包",
                                  "把表情发到群123", "请发个表情，再删除文件"])
def test_save_and_external_actions_do_not_use_expression_exception(text):
    assert not FastDialogueGate().decide(text, capability_groups=["emoji"]).eligible


@pytest.mark.parametrize("channel", [InterfaceChannel.WEB, InterfaceChannel.DESKTOP, InterfaceChannel.CLI])
@pytest.mark.parametrize("raw", ["开头[emoji:得意,邀功]结尾", "[emoji:得意,邀功]"])
async def test_fast_gateway_emits_and_restores_resolved_sequence(tmp_path, channel, raw):
    agent, provider, service = make_agent(tmp_path, [raw])
    agent.session_record = Session(id="local")
    agent.experience_stream = ExperienceStream(tmp_path / "events.db")
    agent.cognitive_ingress = CognitiveIngress(agent.experience_stream)
    gateway = InterfaceGateway(agent)
    result = await gateway.chat(UnifiedMessage(channel=channel, content="发个得意表情"))
    assert result.status == "completed"
    assert len(provider.calls) == 1 and provider.tool_schemas == [None]
    assert "[emoji:属性1,属性2]" in provider.calls[0][0].content
    assert "得意、邀功" in provider.calls[0][0].content
    assert "proud_a" not in provider.calls[0][0].content
    assert "images/a.png" not in provider.calls[0][0].content
    assert "- 属性：开心" not in provider.calls[0][0].content
    assert "[emoji:" not in result.content
    stored = await agent.session_store.get("local")
    assistant = [item for item in stored.conversation.messages if item.role.value == "assistant"]
    expected = ["text", "emoji", "text"] if "开头" in raw else ["emoji"]
    assert [item.segment_type for item in assistant] == expected
    emoji = next(item for item in assistant if item.source == "emoji")
    assert emoji.emoji_id == service.recent_ids[-1]
    assert len(service.recent_ids) == 1
    assert any(message["source"] == "emoji" for message in result.output_messages)
    reply_event = next(event for event in agent.experience_stream.recent()
                       if event.event_type == CognitiveEventType.ASSISTANT_REPLY)
    assert "曾使用表情：得意、邀功" in reply_event.content
    # Pure emoji history is readable to the next FAST turn, without another vision input.
    await agent.cognitive.fast_chat.run_fast_chat("嘿嘿")
    history = provider.calls[-1][1:-1]
    assert any("曾使用表情：得意、邀功" in (item.content or "") for item in history)
    assert not any(item.images for item in history)


@pytest.mark.parametrize("mode", ["disabled", "empty", "unknown"])
async def test_unavailable_emoji_leaves_safe_text_and_no_selection(tmp_path, mode):
    agent, provider, service = make_agent(tmp_path, ["在呢[emoji:不存在的属性]"])
    if mode == "disabled":
        service.enabled = False
    elif mode == "empty":
        service.entries = []
    result = await agent.cognitive.fast_chat.run_fast_chat("小金毛？")
    assert result.content == "在呢"
    assert not service.recent_ids
    assert [segment.type for segment in result.reply_sequence.segments] == ["text"]
    if mode != "unknown":
        assert "当前可用表情" not in provider.calls[0][0].content


async def test_discarded_fast_draft_does_not_select_or_commit_emoji(tmp_path):
    agent, _, service = make_agent(tmp_path, ["污染[emoji:得意,邀功][escalate:tool]"])
    result = await agent.cognitive.fast_chat.run_fast_chat("请读取 README.md")
    assert result.escalated and result.reply_sequence is None
    assert not agent.conversation.messages and not service.recent_ids
    assert not agent.last_emoji_trace


@pytest.mark.parametrize("raw", ["前[emoji:得意,邀功]后", "[emoji:得意,邀功]"])
async def test_qq_fast_transport_selects_once_and_persists_sent_image(tmp_path, raw):
    runtime, agent, provider, service = make_perception(tmp_path, [raw])
    item = observation()
    service.resolve_tags = Mock(wraps=service.resolve_tags)
    transport = SimpleNamespace(action=AsyncMock(return_value={"status": "ok"}))
    received = []
    async def send(target, message):
        received.append(message)
        count = await send_reply(transport, target, message,
                                settings=QQConfig(reply_segment_delay_min_ms=0, reply_segment_delay_max_ms=0,
                                                  interface_settings_path=str(tmp_path / "interface.json")))
        return SendResult(sent=True, segment_count=count)
    await PerceptionSink(runtime, SimpleNamespace(send=send)).emit(item)
    assert runtime.last_fast_gate["eligible"]
    assert len(provider.calls) == 1 and provider.tool_schemas == [None]
    assert service.resolve_tags.call_count == 1 and len(service.recent_ids) == 1
    expected = ["text", "image", "text"] if raw.startswith("前") else ["image"]
    assert [part.type for part in received[0].parts] == expected
    assert [call.args[0] for call in transport.action.await_args_list] == ["send_private_msg"] * len(expected)
    session = await agent.session_store.get("qq/private/8")
    assistant = [item for item in session.conversation.messages if item.role.value == "assistant"]
    assert [item.segment_type for item in assistant] == ["emoji" if kind == "image" else kind for kind in expected]
    selected = next(item for item in assistant if item.source == "emoji")
    image = next(part for part in received[0].parts if part.type == "image")
    assert base64.b64decode(image.data.removeprefix("base64://")) == service.image_path(selected.emoji_id).read_bytes()
    events = agent.experience_stream.recent(10)
    reply = next(event for event in events if event.event_type == CognitiveEventType.ASSISTANT_REPLY)
    assert "曾使用表情：得意、邀功" in reply.content
    assert "[emoji:" not in reply.content
    assert any(segment.get("emoji_id") == selected.emoji_id for segment in reply.metadata["reply_segments"])
    assert not agent.conversation.messages  # QQ does not pollute the local session.
    await runtime.ingest(observation("2"))
    assert any("曾使用表情" in (message.content or "") for message in provider.calls[-1][1:-1])


async def test_missing_or_disabled_asset_never_acknowledges_an_unsent_emoji(tmp_path):
    runtime, agent, _, service = make_perception(tmp_path, ["前[emoji:得意]后"])
    item = observation()
    reply = await runtime.ingest(item)
    assert isinstance(reply, ResolvedReply)
    selected = next(segment for segment in reply.reply_sequence.segments if segment.type == "emoji")
    service.image_path(selected.emoji_id).unlink()
    send = AsyncMock(return_value=SendResult(sent=True, segment_count=2))
    runtime.ingest = AsyncMock(return_value=reply)
    await PerceptionSink(runtime, SimpleNamespace(send=send)).emit(item)
    assert [part.type for part in send.await_args.args[1].parts] == ["text", "text"]
    session = await agent.session_store.get("qq/private/8")
    assert not any(message.source == "emoji" for message in session.conversation.messages)
    service.enabled = False
    pure = ResolvedReply(reply.reply_sequence.model_copy(update={"segments": [selected]}))
    assert pure and not str(pure)
    assert not outbound_message(pure, service).parts
    runtime.ingest = AsyncMock(return_value=pure)
    runtime.reply_sent = AsyncMock()
    send.reset_mock()
    await PerceptionSink(runtime, SimpleNamespace(send=send)).emit(item)
    send.assert_not_awaited()
    runtime.reply_sent.assert_not_awaited()
    assert runtime.last_error == "outbound_reply_empty"
