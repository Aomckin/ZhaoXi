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
    assert '2026-09-06T22:00:00+08:00' in context[1].content
    assert '2026-09-07T00:00:00+08:00' in context[3].to_provider_dict()['content']
    assert '2026-09-07T16:00:00+08:00' in context[4].content
    assert '专注已超过90分钟' in context[3].content
    assert restored.conversation.messages[2].content == '休息一下吧。'
    assert context[0].content.find('当前时间：') >= 0


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
