"""v1.3.2 current anchor, causality, traceability and isolation contracts."""
import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from zhaoxi.cognitive_stream import AttentionRetriever, CognitiveEvent, CognitiveEventType, CognitiveIngress, ExperienceStream
from zhaoxi.cognitive_stream.models import EventPart
from zhaoxi.cognitive_stream.timeline import cognitive_timeline
from zhaoxi.cognitive_stream.turn import CognitiveTurnContext, current_turn, reset_current_turn, set_current_turn
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.core.message import Role, strip_echoed_timeline_header


def event(stream, kind, text, at, *, turn=None, reply=None, cause=None, channel="desktop", role="OWNER"):
    item = CognitiveEvent(event_type=kind, source=channel, channel=channel,
        actor_role=role, content=text, occurred_at=at, received_at=at,
        turn_id=turn, reply_to_event_id=reply, caused_by_event_id=cause,
        privacy_level="OWNER_PRIVATE" if channel == "qq" else "PRIVATE")
    return stream.append(item)


def test_current_anchor_is_once_and_separate_from_recent(tmp_path):
    stream = ExperienceStream(tmp_path / "experience.db")
    now = datetime.now(UTC)
    old = event(stream, CognitiveEventType.USER_MESSAGE, "旧问题", now - timedelta(minutes=2), turn="old")
    trigger = event(stream, CognitiveEventType.USER_MESSAGE, "当前问题", now, turn="current")
    builder = ContextBuilder("朝汐")
    builder.attention_retriever = AttentionRetriever(stream)
    view = Conversation()
    view.add_user("Session 中的陈旧话")
    view.add_user("当前问题")
    token = set_current_turn(CognitiveTurnContext(trigger_event=trigger))
    try:
        messages = builder.build(view)
    finally:
        reset_current_turn(token)
    assert [m.content for m in messages[1:]] == ["旧问题", "当前问题"]
    assert messages[-1].metadata["timeline_scope"] == "current_trigger"
    assert trigger.event_id not in builder.last_cognitive_context["recent_event_ids"]
    assert builder.last_cognitive_context["current_message_ids"] == [trigger.event_id]
    assert old.event_id in builder.last_cognitive_context["recent_event_ids"]


def test_interleaved_replies_stay_in_their_causal_units(tmp_path):
    stream = ExperienceStream(tmp_path / "experience.db")
    now = datetime.now(UTC) - timedelta(minutes=5)
    a = event(stream, CognitiveEventType.EXTERNAL_MESSAGE, "QQ A", now, turn="qq-a", channel="qq")
    b = event(stream, CognitiveEventType.USER_MESSAGE, "Desktop B", now + timedelta(seconds=1), turn="desktop-b")
    ar = event(stream, CognitiveEventType.ASSISTANT_REPLY, "QQ A'", now + timedelta(seconds=2),
               turn="qq-a", reply=a.event_id, channel="qq", role="SELF")
    br = event(stream, CognitiveEventType.ASSISTANT_REPLY, "Desktop B'", now + timedelta(seconds=3),
               turn="desktop-b", reply=b.event_id, role="SELF")
    timeline = cognitive_timeline(stream)
    assert [m.message_id for m in timeline] == [a.event_id, ar.event_id, b.event_id, br.event_id]
    assert timeline[0].metadata["timeline_unit_id"] == timeline[1].metadata["timeline_unit_id"]
    resolved = stream.resolve_timeline_unit("turn:qq-a")
    assert resolved["source_event_ids"] == [a.event_id, ar.event_id]
    assert len(resolved["events"]) == 2
    assert [e.event_id for e in stream.query_by_turn("desktop-b")] == [br.event_id, b.event_id]


def test_source_marker_is_removed_from_final_text():
    assert strip_echoed_timeline_header("[来源: qq] 那句话") == "那句话"
    assert strip_echoed_timeline_header("[External Observation] 看到了") == "看到了"
    assert strip_echoed_timeline_header("[source=desktop] 说过") == "说过"


@pytest.mark.asyncio
async def test_request_scope_isolated_between_concurrent_turns(tmp_path):
    stream = ExperienceStream(tmp_path / "experience.db")
    now = datetime.now(UTC)
    desktop = event(stream, CognitiveEventType.USER_MESSAGE, "桌面", now, turn="desk")
    qq = event(stream, CognitiveEventType.EXTERNAL_MESSAGE, "QQ", now, turn="qq", channel="qq")
    async def worker(trigger, channel):
        token = set_current_turn(CognitiveTurnContext(trigger_event=trigger, output_channel=channel,
                                                     images=(channel,), reply_target=channel))
        try:
            await asyncio.sleep(0)
            turn = current_turn()
            return turn.trigger_event.event_id, turn.output_channel, turn.images, turn.reply_target
        finally:
            reset_current_turn(token)
    results = await asyncio.gather(worker(desktop, "desktop"), worker(qq, "qq"))
    assert results == [(desktop.event_id, "desktop", ("desktop",), "desktop"),
                       (qq.event_id, "qq", ("qq",), "qq")]
    assert current_turn() is None


def test_ambient_group_raw_is_one_traceable_unit(tmp_path):
    stream = ExperienceStream(tmp_path / "experience.db")
    now = datetime.now(UTC) - timedelta(minutes=4)
    ids = []
    for index in range(99):
        item = CognitiveEvent(event_type=CognitiveEventType.EXTERNAL_MESSAGE,
            source="qq", channel="qq", session_id="qq/group/1", actor_role="EXTERNAL",
            actor_name="群友", content=f"第 {index} 条群聊", privacy_level="SOCIAL",
            turn_id=f"raw-{index}", occurred_at=now + timedelta(seconds=index),
            metadata={"conversation_kind": "group", "directed_to_zhaoxi": False})
        stream.append(item)
        ids.append(item.event_id)
    rendered = cognitive_timeline(stream, output_channel="qq", audience="public",
                                  public_session_id="qq/group/1")
    assert len(rendered) <= 2
    units = [stream.resolve_timeline_unit(m.metadata["timeline_unit_id"]) for m in rendered]
    assert {event_id for unit in units for event_id in unit["source_event_ids"]} == set(ids)
    assert sum(len(unit["events"]) for unit in units) == 99


def test_image_raw_can_be_reused_across_channels(tmp_path):
    stream = ExperienceStream(tmp_path / "experience.db")
    now = datetime.now(UTC)
    image = CognitiveEvent(event_type=CognitiveEventType.EXTERNAL_MESSAGE,
        source="qq", channel="qq", actor_role="OWNER", content="看这张图",
        privacy_level="OWNER_PRIVATE", occurred_at=now - timedelta(minutes=1),
        parts=[EventPart(type="image", url="data:image/png;base64,YWJj")])
    stream.append(image)
    trigger = event(stream, CognitiveEventType.USER_MESSAGE, "图里具体是什么？", now, turn="desktop-image")
    builder = ContextBuilder("朝汐")
    builder.attention_retriever = AttentionRetriever(stream)
    view = Conversation()
    view.add_user(trigger.content)
    token = set_current_turn(CognitiveTurnContext(trigger_event=trigger))
    try:
        messages = builder.build(view)
    finally:
        reset_current_turn(token)
    assert messages[1].images == ["data:image/png;base64,YWJj"]
    assert messages[-1].metadata["timeline_scope"] == "current_trigger"


def test_ingress_records_reply_and_tool_causality(tmp_path):
    stream = ExperienceStream(tmp_path / "experience.db")
    ingress = CognitiveIngress(stream)
    trigger = ingress.desktop("算一下", message_id="desktop-turn")
    token = set_current_turn(CognitiveTurnContext(trigger_event=trigger))
    try:
        action = ingress.record(CognitiveEventType.TOOL_ACTION, "调用计算器", source="tool")
        observation = ingress.record(CognitiveEventType.TOOL_OBSERVATION, "结果 2", source="tool",
                                     parent_refs=[action.event_id], caused_by_event_id=action.event_id)
        reply = ingress.record(CognitiveEventType.ASSISTANT_REPLY, "结果是 2", source="desktop")
    finally:
        reset_current_turn(token)
    assert {item.turn_id for item in (trigger, action, observation, reply)} == {"desktop-turn"}
    assert action.caused_by_event_id == trigger.event_id
    assert observation.caused_by_event_id == action.event_id
    assert reply.reply_to_event_id == trigger.event_id
    assert [item.event_id for item in stream.query_by_reply_to(trigger.event_id)] == [reply.event_id]
    assert [item.event_id for item in reversed(stream.query_by_turn("desktop-turn"))] == [
        trigger.event_id, action.event_id, observation.event_id, reply.event_id]


def test_legacy_store_backfills_causal_columns(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    now = datetime.now(UTC)
    owner = CognitiveEvent(event_type=CognitiveEventType.USER_MESSAGE, source="desktop",
                           content="旧输入", actor_role="OWNER", occurred_at=now, received_at=now)
    reply = CognitiveEvent(event_type=CognitiveEventType.ASSISTANT_REPLY, source="desktop",
                           content="旧回复", actor_role="SELF", parent_refs=[owner.event_id],
                           occurred_at=now + timedelta(seconds=1), received_at=now + timedelta(seconds=1))
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE events (event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL,
            source TEXT NOT NULL, channel TEXT, session_id TEXT, actor_id TEXT, actor_role TEXT,
            occurred_at TEXT NOT NULL, received_at TEXT NOT NULL, payload TEXT NOT NULL)""")
        for item in (owner, reply):
            db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)", (
                item.event_id, item.event_type.value, item.source, item.channel, item.session_id,
                item.actor_id, item.actor_role, item.occurred_at.isoformat(),
                item.received_at.isoformat(), item.model_dump_json()))
    stream = ExperienceStream(path)
    assert [item.event_id for item in reversed(stream.query_by_turn(owner.event_id))] == [
        owner.event_id, reply.event_id]
    assert stream.get(reply.event_id).reply_to_event_id == owner.event_id


def test_current_trigger_keeps_full_text_even_when_recent_has_caps(tmp_path):
    stream = ExperienceStream(tmp_path / "experience.db")
    content = "当前问题" + "甲" * 3000
    trigger = event(stream, CognitiveEventType.USER_MESSAGE, content, datetime.now(UTC), turn="long")
    builder = ContextBuilder("朝汐")
    builder.attention_retriever = AttentionRetriever(stream)
    view = Conversation()
    view.add_user(content)
    token = set_current_turn(CognitiveTurnContext(trigger_event=trigger))
    try:
        messages = builder.build(view)
    finally:
        reset_current_turn(token)
    assert messages[-1].content == content
    assert len([m for m in messages if m.message_id == trigger.event_id]) == 1
