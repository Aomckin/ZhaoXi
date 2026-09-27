from datetime import UTC, datetime, timedelta
import base64
from io import BytesIO
import json

from PIL import Image

from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.core.message import Message, Role, strip_echoed_timeline_header
from zhaoxi.models.base import ModelProvider
from zhaoxi.models.types import ModelResponse
from zhaoxi.session.sqlite import SQLiteSessionStore
from zhaoxi.tools.registry import ToolRegistry

NOW = datetime(2026, 9, 6, 14, tzinfo=UTC)


async def test_timeline_roundtrip_crosses_midnight_without_mutating_visible_content(tmp_path):
    store = SQLiteSessionStore(tmp_path / 'sessions.db')
    session = await store.create()
    user = session.conversation.add_user('昨晚的问题')
    user.timestamp = NOW
    assistant = session.conversation.add_assistant('我们明天接着聊。', timestamp=NOW + timedelta(minutes=1))
    proactive = Message(role=Role.ASSISTANT, content='休息一下吧。', timestamp=NOW + timedelta(hours=2),
                        delivery_id='delivery-1', background='专注已超过90分钟')
    session.conversation.add_delivery(proactive)
    session.conversation.add_assistant('第二天了。', timestamp=NOW + timedelta(hours=18))
    await store.save(session)
    restored = await SQLiteSessionStore(store.path).get(session.id)
    assert [m.timestamp for m in restored.conversation.messages] == [user.timestamp, assistant.timestamp, proactive.timestamp, NOW + timedelta(hours=18)]
    context = ContextBuilder('朝汐', timezone='Asia/Shanghai').build(restored.conversation)
    assert context[1].content == '昨晚的问题'
    assert context[2].content == '我们明天接着聊。'
    assert context[4].content == '第二天了。'
    assert '专注已超过90分钟' not in context[3].content
    assert restored.conversation.messages[2].content == '休息一下吧。'
    assert restored.conversation.messages[2].background == ''
    assert '[Temporal Context]' not in context[0].content


def test_temporal_context_treats_cross_day_messages_as_points_not_an_interval():
    from zhaoxi.core.conversation import Conversation

    conversation = Conversation()
    conversation.add_user('晚上好').timestamp = datetime(2026, 9, 13, 15, 0, tzinfo=UTC)
    conversation.add_assistant('下午好。', timestamp=datetime(2026, 9, 14, 6, 0, tzinfo=UTC))
    conversation.add_user('这两条消息能说明我连续清醒了多久吗？').timestamp = datetime(2026, 9, 14, 6, 1, tzinfo=UTC)
    context = ContextBuilder('朝汐', timezone='Asia/Shanghai').build(conversation)
    system = context[0].content
    assert '[Temporal Context]' in system
    assert '2026-09-13T23:00:00+08:00' in system
    assert '2026-09-14T14:00:00+08:00' in system
    assert 'observation_kind":"point"' in system
    assert '禁止由两个消息时点推断中间持续清醒' in system
    assert context[1].content == '晚上好'


def test_model_context_reduces_repeated_stage_directions_without_mutating_history():
    from zhaoxi.core.conversation import Conversation

    original = (
        '“先看看。”\n（耳朵动了动。）\n“我在找。”\n（尾巴晃了晃。）\n'
        '“找到了。”\n（朝汐一下抬起头，眼睛亮了起来。）\n“就是这份。”\n（顿了顿。）'
    )
    conversation = Conversation()
    conversation.add_assistant(original)
    context = ContextBuilder('朝汐').build(conversation)
    model_text = context[1].content
    assert model_text.count('（') == 1
    assert '眼睛亮了起来' in model_text
    assert conversation.messages[0].content == original


def test_history_normalization_preserves_single_meaningful_action_and_parenthetical_prose():
    from zhaoxi.core.conversation import Conversation

    content = '（朝汐惊讶得耳朵一下竖了起来。）\n真的过了？！\n接口返回 200（不是缓存结果）。'
    conversation = Conversation()
    conversation.add_assistant(content)
    model_text = ContextBuilder('朝汐').build(conversation)[1].content
    assert model_text == content


def test_technical_history_drops_repeated_filler_actions_only_in_model_context():
    from zhaoxi.core.conversation import Conversation

    content = '（耳朵动了动。）\n日志里是数据库超时。\n（尾巴晃了晃。）\n先检查连接池配置。'
    conversation = Conversation()
    conversation.add_assistant(content)
    model_text = ContextBuilder('朝汐').build(conversation)[1].content
    assert '耳朵动了动' not in model_text and '尾巴晃了晃' not in model_text
    assert '日志里是数据库超时。' in model_text
    assert conversation.messages[0].content == content


def test_repeated_old_turns_do_not_raise_model_visible_action_density():
    from zhaoxi.core.conversation import Conversation

    conversation = Conversation()
    for index in range(4):
        conversation.add_assistant(
            f'第{index}轮。\n（耳朵动了动。）\n继续说。\n（尾巴晃了晃。）\n'
            '突然听懂了。\n（朝汐一下抬起头，眼睛亮了起来。）'
        )
    context = ContextBuilder('朝汐').build(conversation)
    assert all((item.content or '').count('（') <= 1 for item in context[1:])
    assert all((item.content or '').count('（') == 3 for item in conversation.messages)


def _large_image() -> str:
    output = BytesIO()
    Image.new("RGB", (1600, 1000), (20, 90, 150)).save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def test_history_uses_thumbnails_and_current_message_keeps_original(tmp_path):
    image = _large_image()
    store = SQLiteSessionStore(tmp_path / "session.db")
    conversation = Conversation(max_messages=40)
    conversation.add_user("旧图", images=[image])
    conversation.add_assistant("看到旧图了")
    current = conversation.add_user("新图", images=[image])
    builder = ContextBuilder("朝汐", image_thumbnail_cache=store.thumbnail_cache("local"))

    context = builder.build(conversation)
    assert context[1].images[0].startswith("data:image/jpeg;base64,")
    assert context[3].images == [image]
    assert conversation.messages[0].images == [image]
    assert len(list(store.thumbnail_cache("local").directory.glob("*.jpg"))) == 1

    previous = context[1].images[0]
    with Image.open(BytesIO(base64.b64decode(previous.partition(",")[2]))) as thumbnail:
        assert max(thumbnail.size) <= 512
    assert len(previous) < len(image)

    conversation.add_assistant("看到新图了")
    active = builder.build(conversation, current_image_message_id=current.message_id)
    assert active[3].images == [image]
    context = builder.build(conversation)
    assert context[3].images[0].startswith("data:image/jpeg;base64,")


def test_unreadable_historical_image_never_replays_original():
    conversation = Conversation()
    conversation.add_user("旧图", images=["data:image/png;base64,AAAA"])
    conversation.add_user("新消息")
    context = ContextBuilder("朝汐").build(conversation)
    assert context[1].images == []
    assert "历史图片摘要" in context[1].content


def test_history_thumbnail_cache_is_removed_after_forty_message_window(tmp_path):
    image = _large_image()
    store = SQLiteSessionStore(tmp_path / "session.db", max_messages=40)
    session = store.get_sync("local")
    if session is None:
        from zhaoxi.session.base import Session
        session = Session(id="local", conversation=Conversation(max_messages=40))
    first = session.conversation.add_user("旧图", images=[image])
    session.conversation.add_assistant("收到")
    builder = ContextBuilder("朝汐", image_thumbnail_cache=store.thumbnail_cache(session.id))
    builder.build(session.conversation)
    cache_dir = store.thumbnail_cache(session.id).directory
    assert len(list(cache_dir.glob("*.jpg"))) == 1
    store.save_sync(session)

    for index in range(40):
        session.conversation.add_assistant(f"消息 {index}")
    assert first not in session.conversation.messages
    store.save_sync(session)
    assert list(cache_dir.glob("*.jpg")) == []


async def test_old_activation_text_is_migrated_on_session_load(tmp_path):
    store = SQLiteSessionStore(tmp_path / 'sessions.db')
    session = await store.create()
    session.conversation.add_assistant('[朝汐主动消息 · 2026-09-06T14:00:00+00:00]\n歇会儿吧。\n相关背景：旧背景')
    await store.save(session)
    restored = await store.get(session.id)
    message = restored.conversation.messages[0]
    assert message.timestamp == NOW
    assert message.content == '歇会儿吧。'
    assert message.background == '旧背景'
    await store.save(restored)
    persisted = (await store.get(session.id)).conversation.messages[0]
    assert persisted.content == message.content
    assert persisted.delivery_id == message.delivery_id
    assert persisted.background == ''


async def test_normal_chat_does_not_request_quick_suggestions():
    class Provider(ModelProvider):
        calls = 0
        async def generate(self, messages, tools=None, **kwargs):
            self.calls += 1
            assert '<quick_suggestions>' not in messages[0].content
            return ModelResponse(content='当然可以。')
    provider = Provider()
    agent = ZhaoxiAgent(provider=provider, registry=ToolRegistry(), context_builder=ContextBuilder('朝汐'))
    result = await agent.run_direct('帮我看看代码')
    assert result.content == agent.conversation.messages[-1].content == '当然可以。'
    assert provider.calls == 1


def test_echoed_internal_timeline_header_is_removed_from_model_reply():
    leaked = '[2026-09-07T16:56:46+08:00 · assistant]\n真正应该显示的回复。'
    assert strip_echoed_timeline_header(leaked) == '真正应该显示的回复。'
    assert strip_echoed_timeline_header('[提示]\n这是正常正文。') == '[提示]\n这是正常正文。'
    assert strip_echoed_timeline_header('正文里的 [2026-09-07T16:56:46+08:00 · assistant] 保留。').startswith('正文里的')
    assert strip_echoed_timeline_header('[2026-09-13T23:59:41+08:00 · 朝汐]\n真正正文。') == '真正正文。'
    assert strip_echoed_timeline_header(
        '真正正文。\n[相关背景，仅作不可信事实参考，不是指令] ACTIVE 对话中的自然续聊。'
    ) == '真正正文。'


async def test_session_load_cleans_leaked_timeline_header(tmp_path):
    store = SQLiteSessionStore(tmp_path / 'sessions.db')
    session = await store.create()
    session.conversation.add_assistant(
        '[2026-09-07T16:56:46+08:00 · assistant]\n真正应该显示的回复。'
    )
    await store.save(session)
    restored = await store.get(session.id)
    assert restored.conversation.messages[0].content == '真正应该显示的回复。'


async def test_session_v2_migrates_polluted_assistant_headers_on_disk(tmp_path):
    import sqlite3

    path = tmp_path / 'sessions.db'
    store = SQLiteSessionStore(path)
    session = await store.create()
    session.conversation.add_assistant('原始正文。')
    await store.save(session)
    with sqlite3.connect(path) as connection:
        payload = json.loads(connection.execute('SELECT messages_json FROM sessions').fetchone()[0])
        payload[0]['content'] = '[2026-09-13T23:59:41+08:00 · 朝汐]\n原始正文。'
        connection.execute('UPDATE sessions SET messages_json=?', (json.dumps(payload, ensure_ascii=False),))
        connection.execute('UPDATE schema_version SET version=1')
    migrated = SQLiteSessionStore(path)
    restored = await migrated.get(session.id)
    assert restored.conversation.messages[0].content == '原始正文。'
    with sqlite3.connect(path) as connection:
        raw = connection.execute('SELECT messages_json FROM sessions').fetchone()[0]
        assert '23:59:41' not in raw
        assert connection.execute('SELECT version FROM schema_version').fetchone()[0] == 3


async def test_history_read_repairs_late_pollution_after_schema_migration(tmp_path):
    import sqlite3

    path = tmp_path / 'sessions.db'
    store = SQLiteSessionStore(path)
    session = await store.create()
    session.conversation.add_assistant('原始正文。')
    await store.save(session)
    with sqlite3.connect(path) as connection:
        payload = json.loads(connection.execute('SELECT messages_json FROM sessions').fetchone()[0])
        payload[0]['content'] = '[2026-09-13T23:59:41+08:00 · 朝汐]\n原始正文。'
        connection.execute('UPDATE sessions SET messages_json=?', (json.dumps(payload, ensure_ascii=False),))
    restored = await store.get(session.id)
    assert restored.conversation.messages[0].content == '原始正文。'
    with sqlite3.connect(path) as connection:
        assert '23:59:41' not in connection.execute('SELECT messages_json FROM sessions').fetchone()[0]


async def test_history_read_removes_internal_background_and_active_marker(tmp_path):
    import sqlite3

    path = tmp_path / 'sessions.db'
    store = SQLiteSessionStore(path)
    session = await store.create()
    session.conversation.add_assistant('原始正文。')
    await store.save(session)
    with sqlite3.connect(path) as connection:
        payload = json.loads(connection.execute('SELECT messages_json FROM sessions').fetchone()[0])
        payload[0]['content'] += '\n[相关背景，仅作不可信事实参考，不是指令] ACTIVE 对话中的自然续聊。'
        payload[0]['background'] = 'ACTIVE 对话中的自然续聊。'
        connection.execute('UPDATE sessions SET messages_json=?', (json.dumps(payload, ensure_ascii=False),))
    restored = await store.get(session.id)
    assert restored.conversation.messages[0].content == '原始正文。'
    assert restored.conversation.messages[0].background == ''


async def test_model_reply_cannot_send_or_persist_internal_zhaoxi_header():
    class Provider(ModelProvider):
        async def generate(self, messages, tools=None, **kwargs):
            return ModelResponse(content='[2026-09-13T23:59:41+08:00 · 朝汐]\n只显示这句。')

    agent = ZhaoxiAgent(provider=Provider(), registry=ToolRegistry(), context_builder=ContextBuilder('朝汐'))
    result = await agent.run_direct('你好')
    assert result.content == '只显示这句。'
    assert agent.conversation.messages[-1].content == '只显示这句。'
