"""Engineering guards for the shared loop; real reliability acceptance uses logs."""
import json
import pytest
from pydantic import BaseModel
from conftest import FakeProvider
from zhaoxi.cognitive.coordinator import CognitiveCoordinator
from zhaoxi.cognitive.router import CognitiveRouter
from zhaoxi.config.settings import Settings
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.loop_safety import LoopSafety
from zhaoxi.decision.history import ChoiceHistory
from zhaoxi.interfaces import InterfaceGateway, UnifiedMessage
from zhaoxi.models.types import ModelResponse, ToolCall
from zhaoxi.permission.models import PermissionLevel, SideEffect
from zhaoxi.tools.base import Tool, ToolResult
from zhaoxi.tools.registry import ToolRegistry


class Input(BaseModel):
    value: str = 'done'


class Action(Tool):
    name = 'sample_action'
    group = 'sample'
    description = 'Perform the explicitly requested sample operation.'
    input_model = Input
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.LOCAL_STATE})
    default_confirm_write = False
    def __init__(self):
        self.calls = 0
    async def execute(self, arguments):
        self.calls += 1
        return ToolResult(success=True, content='saved', data={'id': 'saved-id'})


def make(responses, *, history=None):
    registry = ToolRegistry()
    tool = Action()
    registry.register(tool)
    provider, router_provider = FakeProvider(responses), FakeProvider([])
    agent = ZhaoxiAgent(provider=provider, registry=registry, context_builder=ContextBuilder('You are Zhaoxi.'), decision_mode='agency')
    agent.settings = Settings(_env_file=None, unified_reply_enabled=True)
    agent.decision_awareness.history = history
    agent.cognitive = CognitiveCoordinator(agent=agent, router=CognitiveRouter(router_provider))
    return agent, provider, router_provider, tool, InterfaceGateway(agent)


def body(text='hello', **extra):
    return ModelResponse(content=json.dumps({'reply': text, **extra}, ensure_ascii=False))


async def test_chat_one_call_no_router_no_persistent_schemas():
    agent, provider, router, tool, gateway = make([body()])
    response = await gateway.chat(UnifiedMessage(channel='web', content='你好呀'))
    assert response.content == 'hello' and response.activity['result_status'] == 'completed'
    assert len(provider.calls) == 1 and not router.calls and provider.tool_schemas == [None]
    system = provider.calls[0][0].content
    assert 'User Principles' not in system and '可承接反馈的近期选择' not in system
    assert agent.last_action_trace['runtime_metrics']['channel'] == 'web'


async def test_optional_bad_metadata_keeps_body_and_has_no_repair():
    agent, provider, router, tool, gateway = make([body(awareness={'mode': 'wrong'})])
    response = await gateway.chat(UnifiedMessage(channel='web', content='你好呀'))
    assert response.content == 'hello' and len(provider.calls) == 1
    assert response.activity['result_status'] == 'partial_success'


async def test_bad_body_has_one_tool_free_repair_with_recent_context():
    agent, provider, router, tool, gateway = make([ModelResponse(content='{"reply":'), body('repaired')])
    agent.conversation.add_user('The subject is last night.')
    agent.conversation.add_assistant('We discussed the film last night.')
    response = await gateway.chat(UnifiedMessage(channel='web', content='继续说这个'))
    assert response.content == 'repaired' and len(provider.calls) == 2 and tool.calls == 0
    assert provider.tool_schemas[-1] is None
    assert 'We discussed the film' in provider.calls[-1][-1].content
    assert provider.options[-1]['response_format']['json_schema']['name'] == 'reply_repair'


async def test_control_mounts_tool_then_writes_once():
    text = '执行 sample 操作'
    control = {'kind': 'tool', 'group': 'sample', 'reason': 'perform request', 'trigger_span': text}
    agent, provider, router, tool, gateway = make([body('', escalation=control),
        ModelResponse(tool_calls=[ToolCall(id='write', name='sample_action', arguments={})]), body('saved')])
    response = await gateway.chat(UnifiedMessage(channel='web', content=text))
    assert response.content == 'saved' and tool.calls == 1 and len(provider.calls) == 3 and not router.calls
    assert any(schema['function']['name']=='sample_action' for schema in provider.tool_schemas[1])


async def test_invalid_control_does_not_mount_or_execute():
    agent, provider, router, tool, gateway = make([body('', escalation={
        'kind': 'tool', 'group': 'sample', 'reason': 'unrelated', 'trigger_span': 'missing text'}), body('cannot perform that')])
    response = await gateway.chat(UnifiedMessage(channel='web', content='你好呀'))
    assert tool.calls == 0 and len(provider.calls) == 2 and provider.tool_schemas[-1] is None
    assert response.content == 'cannot perform that'


async def test_regenerate_preserves_one_choice(tmp_path):
    history = ChoiceHistory(tmp_path)
    answer = body('rice', awareness={'mode':'PICK', 'decision_kind':'NEW',
        'decision_question':'Choose rice or noodles for dinner tonight.', 'agent_recommendation':'rice'})
    agent, provider, router, tool, gateway = make([answer], history=history)
    first = await gateway.chat(UnifiedMessage(channel='web', content='米粉和泡面选一个'))
    await gateway.regenerate(first.message_id, request_id='regen-choice')
    assert len(history.list()) == 1
    row = history.list()[0]
    history.feedback(row['decision_id'], 'rice', scope=row['scope'], source_message_id='feedback-event')
    count = len((tmp_path/'choice_history.jsonl').read_text(encoding='utf-8').splitlines())
    history.feedback(row['decision_id'], 'rice', scope=row['scope'], source_message_id='feedback-event')
    assert len((tmp_path/'choice_history.jsonl').read_text(encoding='utf-8').splitlines()) == count


async def test_storage_failure_preserves_body_but_never_completed(tmp_path):
    history = ChoiceHistory(tmp_path)
    def fail(*args, **kwargs):
        raise OSError('disk unavailable')
    history.record = fail
    answer = body('rice', awareness={'mode':'PICK', 'decision_kind':'NEW',
        'decision_question':'Choose rice or noodles for dinner tonight.', 'agent_recommendation':'rice'})
    agent, provider, router, tool, gateway = make([answer], history=history)
    response = await gateway.chat(UnifiedMessage(channel='web', content='米粉和泡面选一个'))
    assert response.content.startswith('rice') and '未保存成功' in response.content and response.activity['result_status'] == 'partial_success'
    assert len(provider.calls) == 1


def test_same_decision_read_reused_only_with_same_arguments():
    safety = LoopSafety()
    call = ToolCall(id='one', name='read_decision_context', arguments={'query':'offers', 'sources':['memory']})
    receipt = ToolResult(success=True, content='read', data={'sources': {'memory': [{'ref':'memory:one'}]}})
    safety.observe(call, receipt)
    assert safety.cached_search(call).data == receipt.data
    other = call.model_copy(update={'arguments': {'query':'offers', 'sources':['user_archive']}})
    assert safety.cached_search(other) is None

async def test_public_recall_control_cannot_read_private_data():
    from zhaoxi.cognitive_stream.models import CognitiveEvent,CognitiveEventType
    from zhaoxi.errors import AgentLoopError
    text='查询旧记忆'
    agent, provider, router, tool, gateway = make([body('', escalation={
        'kind':'recall', 'reason':'look up facts', 'trigger_span':text}), body('Private records are unavailable in this channel.')])
    event=CognitiveEvent(event_type=CognitiveEventType.EXTERNAL_MESSAGE,source='qq',channel='qq',
        actor_role='MEMBER',content=text,privacy_level='SOCIAL',metadata={'conversation_kind':'group'})
    response=await agent.run_channel_reply(text,trigger_event=event,audience='public')
    assert response.content=='Private records are unavailable in this channel.'
    assert tool.calls==0 and provider.tool_schemas==[None,None]
    assert 'rejected_capability' in provider.calls[-1][-1].content
    assert 'decision_question' not in provider.calls[0][0].content


async def test_slim_decision_keeps_contract_without_whole_guidance(tmp_path):
    agent, provider, router, tool, gateway = make([],history=ChoiceHistory(tmp_path))
    agent.conversation.add_user('从这两种套餐选哪个？')
    full=agent.context_builder.build(agent.conversation,[],lightweight=True,decision_active=True)
    slim=agent.context_builder.build(agent.conversation,[],lightweight=True,decision_active=True,slim=True)
    assert len(slim[0].content)<len(full[0].content)
    assert 'feedback' in slim[0].content and 'decision_kind' in slim[0].content
    assert 'User Principles 是可修订' not in slim[0].content


def test_decision_read_cache_is_invalidated_by_writes():
    safety=LoopSafety()
    call=ToolCall(id='read',name='read_decision_context',arguments={'query':'today','sources':['agenda']})
    safety.observe(call,ToolResult(success=True,content='read'))
    assert safety.cached_search(call) is not None
    safety.observe(ToolCall(id='write',name='agenda_add',arguments={}),ToolResult(success=True,content='saved'),mutation=True)
    assert safety.cached_search(call) is None


async def test_needed_storage_failure_is_partial_without_observability(tmp_path):
    history=ChoiceHistory(tmp_path)
    def fail(*args,**kwargs):
        raise OSError('disk unavailable')
    history.record=fail
    agent,provider,router,tool,gateway=make([body('rice',awareness={
        'mode':'PICK','decision_kind':'NEW','decision_question':'Choose rice or noodles for dinner tonight.',
        'agent_recommendation':'rice'})],history=history)
    response=await agent.run_natural('米粉和泡面选一个')
    assert response.content.startswith('rice') and '未保存成功' in response.content and response.result_status=='partial_success'


async def test_first_request_preloads_once_and_repair_does_not_repeat():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from zhaoxi.memory.models import MemoryRecord, MemorySearchResult
    from zhaoxi.memory.retrieval import MemoryRetriever
    agent, provider, _, _, gateway = make([ModelResponse(content='{"reply":'), body('restored')])
    fact = MemorySearchResult(record=MemoryRecord(kind='episodic', content='Orion chosen color is blue.',
        normalized_content='orionblue', source='user', source_type='user', confidence=1), text_score=1)
    retriever = MemoryRetriever(SimpleNamespace())
    retriever.preload = AsyncMock(return_value=[fact])
    agent.context_builder.memory_retriever = retriever
    result = await gateway.chat(UnifiedMessage(channel='web', content='Orion color'))
    assert result.content == 'restored'
    assert fact.record.content in provider.calls[0][0].content
    retriever.preload.assert_awaited_once_with('Orion color')
    metrics = agent.last_action_trace['runtime_metrics']
    assert metrics['memory_search_count'] == 1 and metrics['memory_hits'] == 1
    assert len(provider.calls) == 2


@pytest.mark.parametrize('audience,privacy,conversation_kind', [
    ('public', 'SOCIAL', 'group'), ('owner', 'PRIVATE', 'group'), ('owner', 'SOCIAL', 'private')])
async def test_group_or_social_turn_never_preloads_private_memory(audience,privacy,conversation_kind):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from zhaoxi.memory.retrieval import MemoryRetriever
    from zhaoxi.cognitive_stream.models import CognitiveEvent
    from zhaoxi.cognitive_stream.turn import CognitiveTurnContext, set_current_turn, reset_current_turn
    agent, provider, _, _, _ = make([body()])
    retriever = MemoryRetriever(SimpleNamespace())
    retriever.preload = AsyncMock(side_effect=AssertionError('Private read forbidden'))
    agent.context_builder.memory_retriever = retriever
    event = CognitiveEvent(source='qq', channel='qq', event_type='USER_MESSAGE', content='Orion',
        privacy_level=privacy, metadata={'conversation_kind':conversation_kind})
    token = set_current_turn(CognitiveTurnContext(trigger_event=event, audience=audience, output_channel='qq'))
    try:
        agent.conversation.add_user('Orion')
        await agent._run_loop('public-request', user_intent='Orion', audience=audience, output_channel='qq')
    finally:
        reset_current_turn(token)
    retriever.preload.assert_not_awaited()
    assert len(provider.calls) == 1


async def test_optional_local_database_error_is_visible_and_preserves_reply():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from zhaoxi.errors import MemoryError
    from zhaoxi.memory.retrieval import MemoryRetriever
    agent, provider, _, _, gateway = make([body('hello')])
    retriever = MemoryRetriever(SimpleNamespace())
    retriever.preload = AsyncMock(side_effect=MemoryError('database unavailable'))
    agent.context_builder.memory_retriever = retriever
    response = await gateway.chat(UnifiedMessage(channel='web', content='Orion'))
    assert response.content == 'hello' and len(provider.calls) == 1
    assert any(event['event_type'] == 'memory_search_failed' for event in agent.last_action_trace['runtime_metrics']['timeline'])
