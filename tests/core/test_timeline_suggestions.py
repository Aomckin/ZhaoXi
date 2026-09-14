from datetime import UTC, datetime, timedelta
import json

from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.message import Message, Role
from zhaoxi.core.suggestions import QuickSuggestions
from zhaoxi.models.base import ModelProvider
from zhaoxi.models.types import ModelResponse
from zhaoxi.session.sqlite import SQLiteSessionStore
from zhaoxi.proactive.policy import PolicyState
from zhaoxi.tools.registry import ToolRegistry

NOW = datetime(2026, 9, 6, 14, tzinfo=UTC)
VALUES = {'chat': '聊聊刚才的代码吧。', 'action': '帮我定位这个错误。',
          'life': '看看我今天专注多久了。', 'explore': '换个角度解释这段代码吧。'}


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
    assert '专注已超过90分钟' in context[3].content
    assert restored.conversation.messages[2].content == '休息一下吧。'
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
    assert (await store.get(session.id)).conversation.messages[0] == message


def test_suggestions_cache_changes_with_context_and_has_no_extra_llm():
    from zhaoxi.core.conversation import Conversation
    conversation = Conversation()
    cache = QuickSuggestions()
    state = PolicyState()
    first = cache.get(conversation, state, now=NOW)
    assert len(first['suggestions']) == len(set(first['suggestions'])) == 4
    assert cache.get(conversation, state, now=NOW + timedelta(minutes=1)) == first
    assert cache.generated == 1
    state.interaction.receptive(NOW)
    changed = cache.get(conversation, state, focus=True, now=NOW)
    assert changed['suggestions'] != first['suggestions']
    assert '专注' in changed['suggestions'][2]
    assert cache.accept(VALUES, NOW)
    model = cache.get(conversation, state, focus=True, now=NOW)
    assert model['source_context'] == 'model'
    assert model['suggestions'] == list(VALUES.values())
    assert cache.get(conversation, state, now=NOW + timedelta(hours=4))['source_context'] == 'local_context'


async def test_normal_chat_piggybacks_suggestions_without_showing_json():
    class Provider(ModelProvider):
        calls = 0
        async def generate(self, messages, tools=None, **kwargs):
            self.calls += 1
            assert '<quick_suggestions>' in messages[0].content
            return ModelResponse(content='当然可以。<quick_suggestions>' + json.dumps(VALUES, ensure_ascii=False) + '</quick_suggestions>')
    provider = Provider()
    agent = ZhaoxiAgent(provider=provider, registry=ToolRegistry(), context_builder=ContextBuilder('朝汐'))
    result = await agent.run_direct('帮我看看代码')
    assert result.content == agent.conversation.messages[-1].content == '当然可以。'
    assert agent.quick_suggestions.suggestions == list(VALUES.values())
    assert provider.calls == 1


def test_invalid_suggestions_are_hidden_without_replacing_cache():
    cache = QuickSuggestions()
    assert cache.accept(VALUES, NOW)
    assert cache.extract('你好<quick_suggestions>{broken') == '你好'
    assert cache.extract('你好<quick_suggestions>{}</quick_suggestions>') == '你好'
    assert cache.suggestions == list(VALUES.values())


def test_echoed_internal_timeline_header_is_removed_from_model_reply():
    cache = QuickSuggestions()
    leaked = '[2026-09-07T16:56:46+08:00 · assistant]\n真正应该显示的回复。'
    assert cache.extract(leaked) == '真正应该显示的回复。'
    assert cache.extract('[提示]\n这是正常正文。') == '[提示]\n这是正常正文。'
    assert cache.extract('正文里的 [2026-09-07T16:56:46+08:00 · assistant] 保留。').startswith('正文里的')
    assert cache.extract('[2026-09-13T23:59:41+08:00 · 朝汐]\n真正正文。') == '真正正文。'


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
        assert connection.execute('SELECT version FROM schema_version').fetchone()[0] == 2


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


async def test_model_reply_cannot_send_or_persist_internal_zhaoxi_header():
    class Provider(ModelProvider):
        async def generate(self, messages, tools=None, **kwargs):
            return ModelResponse(content='[2026-09-13T23:59:41+08:00 · 朝汐]\n只显示这句。')

    agent = ZhaoxiAgent(provider=Provider(), registry=ToolRegistry(), context_builder=ContextBuilder('朝汐'))
    result = await agent.run_direct('你好')
    assert result.content == '只显示这句。'
    assert agent.conversation.messages[-1].content == '只显示这句。'
