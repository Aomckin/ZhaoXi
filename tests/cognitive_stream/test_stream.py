from datetime import UTC, datetime, timedelta
from zhaoxi.cognitive_stream import CognitiveEvent, CognitiveEventType, ExperienceStream, AttentionRetriever


def event(kind, source, text, minute, **kwargs):
    when = datetime(2026, 9, 27, 12, minute, tzinfo=UTC)
    return CognitiveEvent(event_type=kind, source=source, channel=source, content=text,
                          occurred_at=when, received_at=when, **kwargs)


def test_unified_order_and_source_dedup(tmp_path):
    stream = ExperienceStream(tmp_path / 'experience.db')
    rows = [
        event(CognitiveEventType.USER_MESSAGE, 'desktop', 'A', 1, actor_role='OWNER', session_id='local', source_refs=['desktop:1']),
        event(CognitiveEventType.EXTERNAL_MESSAGE, 'qq', 'B', 2, actor_role='OWNER', session_id='qq/private/owner', source_refs=['qq:2']),
        event(CognitiveEventType.EXTERNAL_MESSAGE, 'qq', 'C', 3, actor_role='THIRD_PARTY', session_id='qq/group/1', source_refs=['qq:3']),
        event(CognitiveEventType.TOOL_OBSERVATION, 'tool', 'D', 4, actor_role='SELF', source_refs=['tool:4']),
        event(CognitiveEventType.USER_MESSAGE, 'desktop', 'E', 5, actor_role='OWNER', session_id='local', source_refs=['desktop:5']),
    ]
    for item in rows:
        stream.append(item)
    assert [item.content for item in reversed(stream.recent())] == list('ABCDE')
    assert stream.append(rows[1].model_copy(update={'event_id': 'duplicate'})).event_id == rows[1].event_id
    assert stream.stats()['total_events'] == 5
    assert [item.content for item in stream.query_by_session('local')] == ['E', 'A']
    assert stream.query_refs(['qq:3'])[0].actor_role == 'THIRD_PARTY'


def test_attention_recalls_cross_channel_with_provenance(tmp_path):
    stream = ExperienceStream(tmp_path / 'experience.db')
    now = datetime.now(UTC)
    qq = CognitiveEvent(event_type=CognitiveEventType.EXTERNAL_MESSAGE, source='qq', channel='qq',
        session_id='qq/private/owner', actor_role='OWNER', trust_level='TRUSTED',
        privacy_level='OWNER_PRIVATE', content='v1.3.2 测试通过了', occurred_at=now,
        received_at=now)
    third = CognitiveEvent(event_type=CognitiveEventType.EXTERNAL_MESSAGE, source='qq', channel='qq',
        session_id='qq/group/1', actor_role='THIRD_PARTY', privacy_level='SOCIAL',
        content='群友说暗苟已经拿 offer 了', occurred_at=now, received_at=now)
    stream.append(qq)
    stream.append(third)
    retriever = AttentionRetriever(stream)
    result = retriever.retrieve('v1.3.2 刚才测试怎么样', session_id='local')
    assert qq.event_id in [item.event_id for item in result.events]
    assert 'Owner' in result.render() and 'qq Owner' not in result.render()
    assert '第三方发言' in result.render()
    public = retriever.retrieve('刚才', session_id='qq/group/1', include_private=False)
    assert qq.event_id not in [item.event_id for item in public.events]


def test_ttl_keeps_recent_owner_and_expires_old_tool(tmp_path):
    stream = ExperienceStream(tmp_path / 'experience.db')
    now = datetime.now(UTC)
    old = now - timedelta(days=8)
    stream.append(CognitiveEvent(event_type=CognitiveEventType.TOOL_OBSERVATION,
        source='tool', content='old', occurred_at=old, received_at=old))
    stream.append(CognitiveEvent(event_type=CognitiveEventType.USER_MESSAGE,
        source='desktop', actor_role='OWNER', content='recent', occurred_at=now, received_at=now))
    assert stream.clear_expired(now) == 1
    assert [item.content for item in stream.recent()] == ['recent']


def test_qq_owner_recalls_desktop_words_without_local_tool_details(tmp_path):
    stream = ExperienceStream(tmp_path / "experience.db")
    now = datetime.now(UTC)
    stream.append(CognitiveEvent(event_type=CognitiveEventType.USER_MESSAGE,
        source="desktop", channel="desktop", actor_role="OWNER", privacy_level="PRIVATE",
        content="今晚继续修朝汐", occurred_at=now, received_at=now))
    stream.append(CognitiveEvent(event_type=CognitiveEventType.TOOL_OBSERVATION,
        source="tool", channel="desktop", actor_role="SELF", privacy_level="PRIVATE",
        content="私人日程细节", occurred_at=now, received_at=now))
    found = AttentionRetriever(stream).retrieve("刚才朝汐修到哪", session_id="qq/private/owner")
    assert "今晚继续修朝汐" in found.render()
    assert "私人日程细节" not in found.render()


def test_ingress_preserves_qq_owner_provenance_and_parts(tmp_path):
    from zhaoxi.cognitive_stream import CognitiveIngress
    from zhaoxi.perception.models import Observation, ObservationPart, TrustLevel
    stream = ExperienceStream(tmp_path / "experience.db")
    ingress = CognitiveIngress(stream)
    observation = Observation(source="qq", source_kind="private_message",
        actor_id="8", actor_role="OWNER", conversation_id="8", conversation_kind="private",
        content="看图", parts=[ObservationPart(type="text", text="看图"),
                              ObservationPart(type="image", url="http://example.test/image")],
        trust_level=TrustLevel.TRUSTED, raw_ref="qq:private:8:42")
    item = ingress.observation(observation, session_id="qq/private/8")
    assert item.actor_role == "OWNER" and item.trust_level == "TRUSTED"
    assert item.privacy_level == "OWNER_PRIVATE" and len(item.parts) == 2
    assert stream.query_refs(["qq:private:8:42"])[0].event_id == item.event_id


def test_cross_channel_reply_survives_bounded_render(tmp_path):
    """Replay the ordering that previously clipped the newest Desktop reply."""
    stream = ExperienceStream(tmp_path / "experience.db")
    now = datetime.now(UTC)
    for index, (channel, kind, content, role, privacy) in enumerate([
        ("qq", CognitiveEventType.EXTERNAL_MESSAGE, "先在 QQ 说话", "OWNER", "OWNER_PRIVATE"),
        ("qq", CognitiveEventType.SOCIAL_SNAPSHOT, "无关群聊" * 100, "SELF", "SOCIAL"),
        ("qq", CognitiveEventType.ASSISTANT_REPLY, "旧的 QQ 回复" * 35, "SELF", "OWNER_PRIVATE"),
        ("desktop", CognitiveEventType.USER_MESSAGE, "主窗口问同步了吗", "OWNER", "PRIVATE"),
        ("desktop", CognitiveEventType.ASSISTANT_REPLY, "主窗口刚刚明确说：现在还是单向同步", "SELF", "PRIVATE"),
    ]):
        stamp = now + timedelta(seconds=index)
        stream.append(CognitiveEvent(event_type=kind, source=channel, channel=channel,
            session_id="local" if channel == "desktop" else "qq/private/owner",
            actor_role=role, privacy_level=privacy, content=content,
            occurred_at=stamp, received_at=stamp))
    result = AttentionRetriever(stream).retrieve("刚刚主窗口那边你不是这么说的",
        session_id="qq/private/owner", max_chars=2400)
    rendered = result.render(600)
    assert "主窗口刚刚明确说：现在还是单向同步" in rendered
    assert "无关群聊" not in rendered
