from datetime import UTC, datetime, timedelta

from zhaoxi.cognitive_stream import (
    AttentionRetriever, CognitiveEvent, CognitiveEventType, ExperienceStream,
)
from zhaoxi.cognitive_stream.timeline import cognitive_timeline
from zhaoxi.cognitive_stream.turn import CognitiveTurnContext, set_current_turn, reset_current_turn
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.core.message import Role


def add(stream, kind, content, when, *, channel="desktop", actor_role="SELF",
        privacy="PRIVATE", session="local"):
    event = CognitiveEvent(
        event_type=kind, source=channel, channel=channel, session_id=session,
        actor_role=actor_role, content=content, privacy_level=privacy,
        occurred_at=when, received_at=when,
    )
    stream.append(event)
    return event


def test_recent_timeline_contains_all_experience_kinds_in_time_order(tmp_path):
    stream = ExperienceStream(tmp_path / "experience.db")
    now = datetime.now(UTC)
    rows = [
        add(stream, CognitiveEventType.USER_MESSAGE, "本地输入", now - timedelta(minutes=8),
            actor_role="OWNER"),
        add(stream, CognitiveEventType.EXTERNAL_MESSAGE, "QQ 输入", now - timedelta(minutes=7),
            channel="qq", actor_role="OWNER", privacy="OWNER_PRIVATE", session="qq/private/owner"),
        add(stream, CognitiveEventType.SOCIAL_SNAPSHOT, "群聊概要", now - timedelta(minutes=6),
            channel="qq", privacy="SOCIAL", session="qq/group/1"),
        add(stream, CognitiveEventType.TOOL_ACTION, "搜索", now - timedelta(minutes=5)),
        add(stream, CognitiveEventType.TOOL_OBSERVATION, "结果" + "X" * 1000,
            now - timedelta(minutes=4)),
        add(stream, CognitiveEventType.WORKFLOW_EVENT, "流程完成", now - timedelta(minutes=3)),
        add(stream, CognitiveEventType.PROACTIVE_EVENT, "主动提醒", now - timedelta(minutes=2)),
        add(stream, CognitiveEventType.ASSISTANT_REPLY, "朝汐回复", now - timedelta(minutes=1)),
    ]
    timeline = cognitive_timeline(stream)
    assert [message.metadata["event_id"] for message in timeline] == [
        event.event_id for event in rows
    ]
    assert [message.role for message in timeline] == [
        Role.USER, Role.USER, Role.EXTERNAL, Role.EXPERIENCE, Role.EXPERIENCE,
        Role.EXPERIENCE, Role.ASSISTANT, Role.ASSISTANT,
    ]
    assert timeline[0].content == "本地输入"
    assert timeline[1].content == "QQ 输入"
    assert timeline[-1].content == "朝汐回复"
    assert "群聊摘要 · qq" in timeline[2].content
    assert "工具结果 · desktop" in timeline[4].content
    assert timeline[4].to_provider_dict()["role"] == "assistant"
    assert len(timeline[4].content) < 550
    assert all(message.metadata["timeline_scope"] == "recent" for message in timeline)


def test_attention_only_adds_older_relevant_events(tmp_path):
    stream = ExperienceStream(tmp_path / "experience.db")
    now = datetime.now(UTC)
    old = add(stream, CognitiveEventType.USER_MESSAGE, "旧版架构约定",
              now - timedelta(days=5), actor_role="OWNER")
    recent = add(stream, CognitiveEventType.USER_MESSAGE, "近期普通发言",
                 now - timedelta(minutes=5), actor_role="OWNER")
    attention = AttentionRetriever(stream)
    timeline = cognitive_timeline(stream, query="旧版架构约定",
                                  attention=attention)
    assert [message.message_id for message in timeline] == [old.event_id, recent.event_id]
    assert [message.metadata["timeline_scope"] for message in timeline] == [
        "attention", "recent",
    ]
    assert [message.message_id for message in cognitive_timeline(stream)] == [recent.event_id]


def test_context_uses_stream_and_not_old_session_history(tmp_path):
    stream = ExperienceStream(tmp_path / "experience.db")
    now = datetime.now(UTC)
    add(stream, CognitiveEventType.EXTERNAL_MESSAGE, "QQ 对话前文",
        now - timedelta(minutes=2), channel="qq", actor_role="OWNER",
        privacy="OWNER_PRIVATE", session="qq/private/owner")
    add(stream, CognitiveEventType.ASSISTANT_REPLY, "我刚才的回复",
        now - timedelta(minutes=1), channel="qq", privacy="OWNER_PRIVATE",
        session="qq/private/owner")
    trigger = add(stream, CognitiveEventType.USER_MESSAGE, "现在继续",
                  now, actor_role="OWNER")
    builder = ContextBuilder("朝汐")
    builder.attention_retriever = AttentionRetriever(stream)
    session = Conversation()
    session.add_user("旧 Session 幻觉")
    session.add_assistant("旧 Session 回复")
    session.add_user("现在继续")
    token = set_current_turn(CognitiveTurnContext(trigger_event=trigger))
    try:
        messages = builder.build(session)
    finally:
        reset_current_turn(token)
    assert [message.content for message in messages[1:]] == [
        "QQ 对话前文", "我刚才的回复", "现在继续",
    ]
    assert [message.role for message in messages[1:]] == [
        Role.USER, Role.ASSISTANT, Role.USER,
    ]
    assert "Relevant Experience" not in messages[0].content
    assert "旧 Session" not in str([message.content for message in messages])


def test_public_timeline_stays_inside_its_social_session(tmp_path):
    stream = ExperienceStream(tmp_path / "experience.db")
    now = datetime.now(UTC)
    add(stream, CognitiveEventType.USER_MESSAGE, "Owner 私聊秘密", now,
        actor_role="OWNER")
    allowed = add(stream, CognitiveEventType.SOCIAL_SNAPSHOT, "当前群摘要", now,
                  channel="qq", privacy="SOCIAL", session="qq/group/1")
    add(stream, CognitiveEventType.SOCIAL_SNAPSHOT, "其他群摘要", now,
        channel="qq", privacy="SOCIAL", session="qq/group/2")
    timeline = cognitive_timeline(
        stream, output_channel="qq", audience="public", public_session_id="qq/group/1",
    )
    assert [message.message_id for message in timeline] == [allowed.event_id]


def test_source_tags_appear_only_for_source_questions(tmp_path):
    stream = ExperienceStream(tmp_path / "experience.db")
    now = datetime.now(UTC)
    add(stream, CognitiveEventType.EXTERNAL_MESSAGE, "那句话", now - timedelta(minutes=1),
        channel="qq", actor_role="OWNER", privacy="OWNER_PRIVATE", session="qq/private/owner")
    trigger = add(stream, CognitiveEventType.USER_MESSAGE, "刚才在 QQ 说了什么", now,
                  actor_role="OWNER")
    builder = ContextBuilder("朝汐")
    builder.attention_retriever = AttentionRetriever(stream)
    view = Conversation()
    view.add_user(trigger.content)
    token = set_current_turn(CognitiveTurnContext(trigger_event=trigger))
    try:
        messages = builder.build(view)
    finally:
        reset_current_turn(token)
    assert messages[1].role is Role.USER
    assert messages[1].content == "[来源: qq] 那句话"
    assert "QQ Owner" not in str(messages)