import asyncio
import base64
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from zhaoxi.adapters.qq.codec import decode
from zhaoxi.adapters.qq.outbound import send_reply
from zhaoxi.config.settings import Settings
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.tools.registry import ToolRegistry
from zhaoxi.core.message import Role
from zhaoxi.models.types import ModelResponse
from zhaoxi.perception.runtime import PerceptionRuntime
from zhaoxi.reliability import MetricRegistry
from zhaoxi.session.sqlite import SQLiteSessionStore


def qq_event(message_id, *, text="hi", kind="private", user_id=8, image=None):
    parts = ([{"type": "text", "data": {"text": text}}] if text else [])
    if image:
        parts.append({"type": "image", "data": {"file": image}})
    return {"post_type": "message", "message_type": kind, "group_id": 123,
            "user_id": user_id, "message_id": message_id,
            "sender": {"nickname": "A"}, "message": parts}


def make_runtime(tmp_path, generate):
    settings = Settings(_env_file=None, perception_db_path=str(tmp_path / "perception.db"),
                        session_db_path=str(tmp_path / "sessions.db"),
                        perception_image_temp_dir=str(tmp_path / "images"),
                        qq_reply_segment_delay_min_ms=0, qq_reply_segment_delay_max_ms=0)
    builder = ContextBuilder("朝汐")
    async def provider_generate(messages, tools=None, **kwargs):
        return await generate(messages, tools)
    agent = ZhaoxiAgent(
        provider=SimpleNamespace(generate=provider_generate),
        registry=ToolRegistry(override_path=tmp_path / "tools.json"),
        context_builder=builder,
    )
    agent.metrics = MetricRegistry()
    agent.conversation_lock = asyncio.Lock()
    agent.session_store = SQLiteSessionStore(settings.session_db_path)
    from zhaoxi.cognitive_stream import CognitiveIngress, ExperienceStream, AttentionRetriever
    agent.experience_stream = ExperienceStream(tmp_path / "experience.db")
    agent.cognitive_ingress = CognitiveIngress(agent.experience_stream)
    agent.attention_retriever = AttentionRetriever(agent.experience_stream)
    builder.attention_retriever = agent.attention_retriever
    return PerceptionRuntime(settings, agent), agent


@pytest.mark.asyncio
async def test_external_sessions_and_shared_self(tmp_path):
    seen = []
    async def generate(messages, tools):
        seen.append(messages)
        if "外部认知 Planner" in messages[0].content:
            return ModelResponse(content='{"reply":true,"reason":"reply"}')
        return ModelResponse(content="收到")
    runtime, agent = make_runtime(tmp_path, generate)
    first = decode(qq_event(1, text="第一轮"), self_id="42", owner_id="8")
    assert await runtime.ingest(first) == "收到"
    await runtime.reply_sent(first, "收到", 1)
    second = decode(qq_event(2, text="第二轮"), self_id="42", owner_id="8")
    assert await runtime.ingest(second) == "收到"
    session = await agent.session_store.get("qq/private/8")
    assert session and [m.role for m in session.conversation.messages] == [
        Role.USER, Role.ASSISTANT, Role.USER]
    assert await agent.session_store.get("local") is None
    assert session.channel_metadata["conversation_kind"] == "private"
    assert session.recent_message_refs == [first.raw_ref, second.raw_ref]
    assert any("第一轮" in m.content for m in seen[-1] if m.content)
    assert "已通过 QQ 私聊回复" not in runtime.shared_context()
    assert "第一轮" not in runtime.shared_context()
    from zhaoxi.core.conversation import Conversation
    assert "已通过 QQ 私聊回复" not in agent.context_builder.build(Conversation())[0].content


@pytest.mark.asyncio
async def test_planner_can_skip_and_image_reaches_both_calls(tmp_path):
    seen = []
    async def generate(messages, tools):
        seen.append(messages)
        if "外部认知 Planner" in messages[0].content:
            return ModelResponse(content='{"reply":true,"reason":"image"}')
        return ModelResponse(content="看到了")
    runtime, _ = make_runtime(tmp_path, generate)
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"abc").decode()
    item = decode(qq_event(3, text="", image="base64://" + png), self_id="42")
    assert await runtime.ingest(item) == "看到了"
    assert len(seen) == 1
    assert any(m.images for m in seen[0])
    assert runtime.multimodal_input_count == 1
    assert item.parts[0].type == "image"

    async def skip(messages, tools):
        return ModelResponse(content='{"reply":false,"reason":"noise"}')
    runtime.agent.provider.generate = skip
    assert await runtime.ingest(decode(qq_event(4, text="重复噪声"), self_id="42")) is None


@pytest.mark.asyncio
async def test_third_party_candidate_rejected_and_ambient_once(tmp_path):
    calls = []
    async def generate(messages, tools):
        calls.append(messages)
        return ModelResponse(content='{"reply":false,"cognition_candidate":"暗苟明天去深圳","memory_candidates":["暗苟明天去深圳"],"reason":"claim"}')
    runtime, agent = make_runtime(tmp_path, generate)
    group = decode(qq_event(5, text="@朝汐 暗苟明天去深圳", kind="group"), self_id="42")
    group.directed_to_zhaoxi = True
    assert await runtime.ingest(group) is None
    assert runtime.planner.rejected_candidate_count == 0
    assert not hasattr(agent, "memory_service")
    runtime.settings.perception_batch_max_messages = 2
    for n in (6, 7):
        await runtime.ingest(decode(qq_event(n, text="群消息", kind="group"), self_id="42"))
    before = len(calls)
    assert await runtime.process_pending_snapshot() == 1
    assert len(calls) == before + 1
    assert await runtime.process_pending_snapshot() == 0


@pytest.mark.asyncio
async def test_qq_sends_each_text_segment_and_emoji(tmp_path):
    image = tmp_path / "emoji.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nabc")
    service = SimpleNamespace(resolve_tags=lambda tags: SimpleNamespace(
        status="matched", emoji_id="one"), image_path=lambda emoji_id: image)
    transport = SimpleNamespace(action=AsyncMock(return_value={"status": "ok"}))
    item = decode(qq_event(8), self_id="42")
    settings = Settings(_env_file=None, qq_reply_segment_delay_min_ms=0,
                        qq_reply_segment_delay_max_ms=0)
    count = await send_reply(transport, item, "第一段\n\n第二段[emoji:开心]\n\n第三段",
                             settings=settings, emoji_service=service)
    assert count == 4
    assert transport.action.await_count == 4
    messages = [call.args[1]["message"] for call in transport.action.await_args_list]
    assert [part[-1]["type"] for part in messages] == ["text", "text", "image", "text"]
    assert messages[0][0]["type"] == "reply"
    assert all(len(message) == 1 for message in messages[1:])


@pytest.mark.asyncio
async def test_owner_candidates_pass_existing_guards(tmp_path):
    from zhaoxi.current_cognition.service import CurrentCognitionService
    from zhaoxi.current_cognition.store import CurrentCognitionStore
    from zhaoxi.perception.planner import ExternalCognitionDecision
    async def unused(messages, tools):
        raise AssertionError("no model call")
    runtime, agent = make_runtime(tmp_path, unused)
    agent.current_cognition = CurrentCognitionService(CurrentCognitionStore(tmp_path / "cognition.db"))
    memory = SimpleNamespace(remember=AsyncMock(return_value=SimpleNamespace(created=True)))
    agent.memory_service = memory
    item = decode(qq_event(9, text="今晚先修朝汐，以后记得我不喜欢辣椒"),
                  self_id="42", owner_id="8")
    await runtime.planner.apply_candidates(item, ExternalCognitionDecision(
        cognition_candidate="今晚先修朝汐", memory_candidates=["我不喜欢辣椒"]))
    assert "今晚先修朝汐" in agent.current_cognition.state().attention
    assert agent.current_cognition.state().last_processed_message_id is None
    memory.remember.assert_awaited_once()
    candidate = memory.remember.await_args.args[0]
    assert candidate.metadata["external_source"] == "OWNER_EXTERNAL"
    assert candidate.source_ref == item.raw_ref


def test_runtime_state_stale_across_processes(tmp_path):
    import sqlite3
    from datetime import UTC, datetime, timedelta
    from zhaoxi.perception.ledger import InteractionLedger
    path = tmp_path / "shared.db"
    first = InteractionLedger(path)
    first.save_runtime_state({"perception": {"enabled": True},
                              "qq": {"connected": True, "identity_verified": True}})
    assert InteractionLedger(path).runtime_state()["qq"]["connected"]
    with sqlite3.connect(path) as db:
        db.execute("UPDATE runtime_self_state SET updated_at=? WHERE id=1",
                   ((datetime.now(UTC) - timedelta(minutes=3)).isoformat(),))
    state = InteractionLedger(path).runtime_state()
    assert not state["qq"]["connected"] and state["qq"]["stale"]



@pytest.mark.asyncio
async def test_image_resolver_rejects_paths_and_wrong_local_port(tmp_path):
    from zhaoxi.perception.images import ImageResolver
    resolver = ImageResolver(tmp_path / "images", max_bytes=128, ttl_hours=1,
                             trusted_host="127.0.0.1", trusted_port=3002)
    assert await resolver.resolve({"file": str(tmp_path / "secret.png")}) is None
    assert await resolver.resolve({"url": "http://127.0.0.1:3001/private"}) is None
    assert await resolver.resolve({"file": "base64://" +
        base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 200).decode()}) is None


@pytest.mark.asyncio
async def test_owner_image_survives_malformed_planner_json(tmp_path):
    seen = []
    async def generate(messages, tools):
        seen.append(messages)
        if "外部认知 Planner" in messages[0].content:
            return ModelResponse(content="看见图片了，但忘了 JSON")
        return ModelResponse(content="图里是一只猫")
    runtime, agent = make_runtime(tmp_path, generate)
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"abc").decode()
    item = decode(qq_event(10, text="这张图里有什么？", image="base64://" + png),
                  self_id="42", owner_id="8")
    assert await runtime.ingest(item) == "图里是一只猫"
    assert len(seen) == 2
    assert all(any(m.images for m in call) for call in seen)
    assert "已按配置核验为暗苟本人" not in seen[1][0].content
    assert runtime.planner.cognition_candidate_count == 0
    assert runtime.planner.memory_candidate_count == 0
    assert runtime.store.counts().get("FAILED", 0) == 0
    session = await agent.session_store.get("qq/private/8")
    assert session and "这张图里有什么" in session.conversation.messages[-1].content


@pytest.mark.asyncio
async def test_owner_adjacent_image_and_text_use_same_visual_input(tmp_path):
    seen = []
    async def generate(messages, tools):
        seen.append(messages)
        if "外部认知 Planner" in messages[0].content:
            return ModelResponse(content='{"reply":true}')
        return ModelResponse(content="一只猫")
    runtime, _ = make_runtime(tmp_path, generate)
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"abc").decode()
    image = decode(qq_event(11, text="", image="base64://" + png), self_id="42", owner_id="8")
    text = decode(qq_event(12, text="这张图里有什么？"), self_id="42", owner_id="8")
    assert await runtime.ingest(image) == "一只猫"
    assert await runtime.ingest(text) == "一只猫"
    assert len(seen) == 4
    assert all(any(message.images for message in call) for call in seen)
    assert any(message.role == Role.USER and message.images for message in seen[-1])
    assert "昵称 A 就是暗苟的 QQ 昵称" not in seen[-1][0].content


@pytest.mark.asyncio
async def test_qq_external_debounce_merges_adjacent_image_and_text(tmp_path):
    from zhaoxi.adapters.qq.adapter import QQAdapter
    path = tmp_path / "interface-settings.json"
    path.write_text('{"external_input_debounce_seconds":0.05,"external_reply_interval_seconds":0}', encoding="utf-8")
    settings = Settings(_env_file=None, interface_settings_path=str(path))
    runtime = SimpleNamespace(agent=SimpleNamespace(metrics=MetricRegistry()),
                              ingest=AsyncMock(return_value=None))
    adapter = QQAdapter(runtime, settings)
    adapter.transport.identity_verified = True
    adapter.transport.self_id = "42"
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"abc").decode()
    first = asyncio.create_task(adapter.on_event(qq_event(101, text="", image="base64://" + png)))
    await asyncio.sleep(0.01)
    await adapter.on_event(qq_event(102, text="这张图里有什么？"))
    await first
    runtime.ingest.assert_awaited_once()
    item = runtime.ingest.await_args.args[0]
    assert item.content == "这张图里有什么？"
    assert [part.type for part in item.parts] == ["image", "text"]
    assert item.metadata["merged_refs"] == ["qq:private:8:101", "qq:private:8:102"]


@pytest.mark.asyncio
async def test_qq_external_reply_delay_uses_desktop_setting(tmp_path, monkeypatch):
    from zhaoxi.adapters.qq import outbound
    path = tmp_path / "interface-settings.json"
    path.write_text('{"external_reply_interval_seconds":1.2}', encoding="utf-8")
    settings = Settings(_env_file=None, interface_settings_path=str(path))
    transport = SimpleNamespace(action=AsyncMock(return_value={"status": "ok"}))
    sleep = AsyncMock()
    monkeypatch.setattr(outbound.asyncio, "sleep", sleep)
    item = decode(qq_event(103), self_id="42")
    assert await outbound.send_reply(transport, item, "第一段\n\n第二段", settings=settings) == 2
    sleep.assert_awaited_once_with(1.2)


@pytest.mark.asyncio
async def test_external_debounce_keeps_actors_and_ambient_separate(tmp_path):
    from zhaoxi.adapters.qq.adapter import QQAdapter
    path = tmp_path / "interface-settings.json"
    path.write_text('{"external_input_debounce_seconds":0.02}', encoding="utf-8")
    settings = Settings(_env_file=None, interface_settings_path=str(path))
    runtime = SimpleNamespace(agent=SimpleNamespace(metrics=MetricRegistry()))
    adapter = QQAdapter(runtime, settings)
    one = decode(qq_event(201, user_id=8), self_id="42", owner_id="8")
    two = decode(qq_event(202, user_id=9), self_id="42", owner_id="8")
    first, second = await asyncio.gather(adapter._debounce_direct(one), adapter._debounce_direct(two))
    assert first is one and second is two
    ambient = decode(qq_event(203, kind="group", user_id=9), self_id="42", owner_id="8")
    assert await adapter._debounce_direct(ambient) is ambient


@pytest.mark.asyncio
async def test_owner_qq_receives_recent_desktop_reply_from_stream(tmp_path):
    from zhaoxi.cognitive_stream import CognitiveIngress, ExperienceStream, AttentionRetriever
    from zhaoxi.cognitive_stream.models import CognitiveEventType
    seen = []
    async def generate(messages, tools):
        seen.append(messages)
        if "外部认知 Planner" in messages[0].content:
            return ModelResponse(content='{"reply":true,"reason":"cross channel"}')
        return ModelResponse(content="我看到主窗口刚才的回复了")
    runtime, agent = make_runtime(tmp_path, generate)
    stream = ExperienceStream(tmp_path / "experience.db")
    ingress = CognitiveIngress(stream)
    agent.experience_stream = stream
    agent.cognitive_ingress = ingress
    agent.attention_retriever = AttentionRetriever(stream)
    agent.context_builder.attention_retriever = agent.attention_retriever
    owner = ingress.desktop("主窗口问同步了吗", message_id="desktop-test")
    ingress.record(CognitiveEventType.ASSISTANT_REPLY,
        "主窗口刚才明确说：现在还是单向同步", source="desktop", channel="web",
        session_id="local", parent_refs=[owner.event_id])
    item = decode(qq_event(42, text="刚刚主窗口那边你不是这么说的"),
                  self_id="42", owner_id="8")
    assert await runtime.ingest(item) == "我看到主窗口刚才的回复了"
    assert any("主窗口刚才明确说：现在还是单向同步" in (message.content or "")
               for message in seen[-1])

@pytest.mark.asyncio
async def test_qq_reply_is_desktop_assistant_history_from_stream(tmp_path):
    seen = []
    async def generate(messages, tools):
        seen.append(messages)
        if "外部认知 Planner" in messages[0].content:
            return ModelResponse(content='{"reply":true}')
        return ModelResponse(content="QQ 上的回复")
    runtime, agent = make_runtime(tmp_path, generate)
    item = decode(qq_event(99, text="先在 QQ 说一句"), self_id="42", owner_id="8")
    content = await runtime.ingest(item)
    assert content == "QQ 上的回复"
    await runtime.reply_sent(item, content, 1)
    trigger = agent.cognitive_ingress.desktop("现在在桌面继续", message_id="desktop-after-qq")
    from zhaoxi.cognitive_stream.turn import CognitiveTurnContext, set_current_turn, reset_current_turn
    from zhaoxi.core.conversation import Conversation
    view = Conversation()
    view.add_user("现在在桌面继续")
    token = set_current_turn(CognitiveTurnContext(trigger_event=trigger))
    try:
        messages = agent.context_builder.build(view)
    finally:
        reset_current_turn(token)
    assert any(message.role is Role.ASSISTANT and message.content.endswith("QQ 上的回复")
               for message in messages)
    assert all("Self Event:" not in (message.content or "") for message in messages)


@pytest.mark.asyncio
async def test_non_owner_first_reply_then_bot_loop_stops(tmp_path):
    seen = []
    async def generate(messages, tools):
        seen.append(messages)
        if "外部认知 Planner" in messages[0].content:
            return ModelResponse(content='{"reply":true,"reason":"owner"}')
        return ModelResponse(content="这是一次答复")
    runtime, agent = make_runtime(tmp_path, generate)

    bot_event = qq_event(201, text="请问你是谁？", user_id=9)
    bot_event["sender"]["is_bot"] = True
    bot = decode(bot_event, self_id="42", owner_id="8")
    assert bot.metadata["sender_is_bot"] is True
    assert await runtime.ingest(bot) == "这是一次答复"
    assert len(seen) == 1  # Non-owner first request goes directly to final reply.
    await runtime.reply_sent(bot, "这是一次答复", 1)

    bot_followup = decode(qq_event(202, text="请问还有呢？", user_id=9),
                          self_id="42", owner_id="8")
    bot_followup.metadata["sender_is_bot"] = True
    assert await runtime.ingest(bot_followup) is None
    assert runtime.last_reply_gate["reason"] == "bot_already_answered"
    assert len(seen) == 1
    assert agent.experience_stream.query_refs([bot_followup.raw_ref])

    greeting = decode(qq_event(203, text="你好", user_id=10), self_id="42", owner_id="8")
    assert await runtime.ingest(greeting) is None
    assert runtime.last_reply_gate["reason"] == "no_explicit_request"
    assert len(seen) == 1

    question = decode(qq_event(204, text="请问你能解释一下吗？", user_id=10),
                      self_id="42", owner_id="8")
    assert await runtime.ingest(question) == "这是一次答复"
    assert len(seen) == 2
    await runtime.reply_sent(question, "这是一次答复", 1)
    followup = decode(qq_event(205, text="那请问下一题呢？", user_id=10),
                      self_id="42", owner_id="8")
    assert await runtime.ingest(followup) is None
    assert runtime.last_reply_gate["reason"] == "recent_external_reply"
    assert len(seen) == 2

    owner = decode(qq_event(206, text="请问下一题呢？", user_id=8),
                   self_id="42", owner_id="8")
    assert await runtime.ingest(owner) == "这是一次答复"
    assert runtime.last_reply_gate["blocked"] is False
    assert len(seen) == 4


def test_non_owner_cooldown_is_actor_and_short_session_window(tmp_path):
    from datetime import timedelta
    from zhaoxi.cognitive_stream import CognitiveIngress, ExperienceStream, CognitiveEventType
    from zhaoxi.perception.reply_guard import non_owner_reply_block_reason
    stream = ExperienceStream(tmp_path / "experience.db")
    ingress = CognitiveIngress(stream)
    def group_question(message_id, actor_id):
        item = decode(qq_event(message_id, text="请问这是什么？", kind="group", user_id=actor_id),
                      self_id="42", owner_id="8")
        item.directed_to_zhaoxi = True
        return item
    first = group_question(301, 9)
    trigger = ingress.observation(first, session_id="qq/group/123")
    reply = ingress.record(CognitiveEventType.ASSISTANT_REPLY, "一次回答", source="qq",
                           session_id="qq/group/123", parent_refs=[trigger.event_id],
                           reply_to_event_id=trigger.event_id, turn_id=trigger.turn_id,
                           metadata={"external_reply": True, "external_actor_id": first.actor_id})
    other = group_question(302, 10)
    assert non_owner_reply_block_reason(other, stream,
        now=reply.received_at + timedelta(seconds=30)) == "recent_external_reply"
    assert non_owner_reply_block_reason(other, stream,
        now=reply.received_at + timedelta(seconds=46)) is None
    same = group_question(303, 9)
    assert non_owner_reply_block_reason(same, stream,
        now=reply.received_at + timedelta(minutes=4)) == "recent_external_reply"
    assert non_owner_reply_block_reason(same, stream,
        now=reply.received_at + timedelta(minutes=6)) is None


def test_known_bot_gets_one_reply_until_owner_intervenes(tmp_path):
    from datetime import timedelta
    from zhaoxi.cognitive_stream import CognitiveIngress, ExperienceStream, CognitiveEventType
    from zhaoxi.perception.reply_guard import non_owner_reply_block_reason
    stream = ExperienceStream(tmp_path / "experience.db")
    ingress = CognitiveIngress(stream)
    def group_item(message_id, actor_id, text="请问这是什么？"):
        item = decode(qq_event(message_id, text=text, kind="group", user_id=actor_id),
                      self_id="42", owner_id="8")
        item.directed_to_zhaoxi = True
        return item
    bot = group_item(401, 9)
    assert non_owner_reply_block_reason(bot, stream, known_bot_ids={"9"}) is None
    trigger = ingress.observation(bot, session_id="qq/group/123")
    reply = ingress.record(CognitiveEventType.ASSISTANT_REPLY, "一次回答", source="qq",
                           session_id="qq/group/123", parent_refs=[trigger.event_id],
                           reply_to_event_id=trigger.event_id, turn_id=trigger.turn_id,
                           metadata={"external_reply": True, "external_actor_id": "9"})
    next_bot = group_item(402, 9)
    assert non_owner_reply_block_reason(next_bot, stream,
        now=reply.received_at + timedelta(minutes=6), known_bot_ids={"9"}) == "bot_already_answered"
    owner = group_item(403, 8, "朝汐，继续")
    ingress.observation(owner, session_id="qq/group/123")
    assert non_owner_reply_block_reason(next_bot, stream,
        now=reply.received_at + timedelta(minutes=6), known_bot_ids={"9"}) is None
