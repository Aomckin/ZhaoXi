"""Decision Learning contracts with synthetic data and no live model/account."""
import asyncio
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo
import httpx
import pytest
from conftest import FakeProvider
from zhaoxi.models.types import ModelResponse
from zhaoxi.decision.models import DecisionAwarenessTrace
from zhaoxi.decision.learning_models import DecisionJournalEntry, FeedbackLabel
from zhaoxi.decision.history import ChoiceHistory
from zhaoxi.decision.journal import DecisionJournalStore
from zhaoxi.decision.learning import DecisionLearning
from zhaoxi.decision.follow_up import DecisionFollowUp
from zhaoxi.decision.user_principles import UserPrincipleStore, DecisionPrincipleArchiveProvider
from zhaoxi.config.settings import Settings

SCOPE = 'owner:desktop:local'


def stack(tmp_path, responses=()):
    history = ChoiceHistory(tmp_path / 'decisions')
    journal = DecisionJournalStore(tmp_path / 'decisions')
    principles = UserPrincipleStore(tmp_path / 'principles')
    provider = FakeProvider(list(responses))
    return DecisionLearning(history, journal, principles, provider)


def episode(learning, identity='one', mode='ADVISE', label='GOOD', **metadata):
    trace = DecisionAwarenessTrace(mode=mode, agent_recommendation='出去活动', **metadata)
    learning.history.record(identity, trace, '低精力下午出去活动还是继续项目', scope=SCOPE)
    if label:
        learning.history.feedback(identity, scope=SCOPE, outcome_label=label, outcome_text='回来状态好多了')
    return learning.history.get(identity)


def reflection(action='CREATE', **fields):
    return ModelResponse(content=json.dumps({'decision_id':'one', 'learnable':True, 'summary':'休息后状态更好',
        'reason':'有明确体验反馈，暂时可推广到同类低精力状态', 'conditions':['无紧急 deadline', '已经低效很久'],
        'journal_action':action, 'title':'低精力时换个环境', 'statement':'这种时候暂时倾向出去活动',
        'confidence_delta':.08, **fields}, ensure_ascii=False))


def seed(learning, **fields):
    return learning.journal.create(DecisionJournalEntry(**{'title':'低精力状态', 'statement':'换个环境可能更好', **fields}).model_dump(mode='json'))


@pytest.mark.parametrize('label', list(FeedbackLabel))
def test_feedback_all_labels_preserves_natural_text_and_cancels_followup(tmp_path, label):
    learning = stack(tmp_path)
    row = episode(learning, label=None, follow_up_policy='SCHEDULED', follow_up_after=datetime.now(UTC))
    before = (learning.history.directory / 'choice_history.jsonl').read_bytes()
    event = learning.history.feedback('one', scope=SCOPE, outcome_label=label, outcome_text='真实反馈原话')
    after = (learning.history.directory / 'choice_history.jsonl').read_bytes()
    assert after.startswith(before) and event['schema_version'] == 3
    row = learning.history.get('one')
    assert row['feedback']['label'] == label and row['feedback']['text'] == '真实反馈原话'
    assert row['follow_up_status'] == 'ANSWERED' and row['user_final_choice'] is None


def test_feedback_scope_and_channel_rejected_no_mutation(tmp_path):
    learning = stack(tmp_path);episode(learning, label=None)
    path = learning.history.directory / 'choice_history.jsonl';before = path.read_bytes()
    for scope in ['owner:mobile:local', 'owner:desktop:other', 'public:desktop:local']:
        with pytest.raises(ValueError):
            learning.history.feedback('one', scope=scope, outcome_label='GOOD')
    assert path.read_bytes() == before


def test_legacy_v2_and_torn_tail_replay_without_rewriting(tmp_path):
    history = ChoiceHistory(tmp_path)
    text = json.dumps({'decision_id':'old','schema_version':2,'scope':SCOPE,'timestamp':datetime.now(UTC).isoformat(),
                       'summary':'菜单','mode':'PICK','suggestion':'A'})+'\n'+json.dumps({'event':'feedback',
                       'decision_id':'old','scope':SCOPE,'user_final_choice':'B','overridden':True,'outcome':'不错'})+'\n{"bad"'
    (tmp_path / 'choice_history.jsonl').write_text(text,encoding='utf-8')
    old = history.get('old');assert old['outcome']=='不错' and old['follow_up_policy']=='PASSIVE'
    history.feedback('old',scope=SCOPE,outcome_label='NO_DIFFERENCE',outcome_text='两个都一样')
    assert (tmp_path/'choice_history.jsonl').read_text(encoding='utf-8').startswith(text)
    assert ChoiceHistory(tmp_path).get('old')['feedback']['label']=='NO_DIFFERENCE'


@pytest.mark.parametrize('audience,privacy', [('public','PRIVATE'), ('owner','PUBLIC'), ('owner','SOCIAL')])
async def test_private_stores_and_prompt_do_not_expose_in_public(tmp_path,audience,privacy):
    from zhaoxi.cognitive_stream.models import CognitiveEvent,CognitiveEventType
    from zhaoxi.cognitive_stream.turn import CognitiveTurnContext,set_current_turn,reset_current_turn
    from zhaoxi.decision.awareness import DecisionAwareness
    from zhaoxi.core.conversation import Conversation
    learning=stack(tmp_path);episode(learning);seed(learning)
    awareness=DecisionAwareness(history=learning.history);awareness.journal=learning.journal
    event=CognitiveEvent(event_type=CognitiveEventType.USER_MESSAGE,source='qq',privacy_level=privacy)
    token=set_current_turn(CognitiveTurnContext(trigger_event=event,audience=audience))
    try:
        for call in [learning.history.list,learning.journal.list,learning.journal.reflections,learning.principles.list]:
            with pytest.raises(PermissionError):call()
        with pytest.raises(PermissionError):await learning.reflect('one')
        prompt=awareness.prompt(Conversation())
        assert '低精力下午' not in prompt and awareness.pending_choice(Conversation()) is None
    finally:reset_current_turn(token)


async def test_create_is_provisional_and_does_not_modify_user_principles(tmp_path):
    learning=stack(tmp_path,[reflection()]);episode(learning)
    root=learning.principles.directory;root.mkdir()
    text=json.dumps({'id':'explicit','statement':'保持主线','source':{'type':'archive','path':'user/protocol.md'}})
    (root/'explicit.json').write_text(text,encoding='utf-8')
    result=await learning.reflect('one');entry=learning.journal.get(result['target_journal_id'])
    assert entry['status']=='UNCERTAIN' and entry['support_count']==1
    assert entry['source_decision_ids']==['one'] and len(entry['source_feedback_ids'])==1
    assert (root/'explicit.json').read_text(encoding='utf-8')==text
    assert learning.history.get('one')['reflected'] and len(learning.provider.calls)==1
    await learning.reflect('one');assert len(learning.provider.calls)==1
    assert len(learning.journal.revisions())==1


@pytest.mark.parametrize('label,action',[('GOOD','SUPPORT'),('BAD','WEAKEN'),('BAD','REFINE'),('MIXED','REFINE'),('BAD','CONFLICT'),('BAD','RETIRE')])
async def test_reflection_actions_and_bounded_delta(tmp_path,label,action):
    learning=stack(tmp_path);entry=seed(learning,confidence=.76,status='ACTIVE')
    learning.provider.responses.append(reflection(action,target_journal_id=entry['id'],confidence_delta=-.9,
        statement='需要先检查现实约束',exceptions=['临近硬 deadline']))
    episode(learning,label=label,journal_ids=[entry['id']]);result=await learning.reflect('one')
    updated=learning.journal.get(entry['id'])
    assert result['confidence_delta']==-.15 and updated['confidence']==pytest.approx(.61)
    if action=='REFINE':assert updated['exceptions']==['临近硬 deadline']
    if action=='CONFLICT':assert updated['status']=='CONFLICTED'
    if action=='RETIRE':assert updated['status']=='RETIRED'


@pytest.mark.parametrize('state',['LOCKED','PINNED'])
async def test_manual_state_keeps_body_confidence_adds_conflict_evidence(tmp_path,state):
    learning=stack(tmp_path);entry=seed(learning,manual_state=state,confidence=.8,status='ACTIVE')
    learning.provider.responses.append(reflection('REFINE',target_journal_id=entry['id'],statement='不应覆盖',confidence_delta=-.15))
    episode(learning,label='BAD',journal_ids=[entry['id']]);await learning.reflect('one')
    updated=learning.journal.get(entry['id']);assert updated['statement']==entry['statement']
    assert updated['confidence']==.8 and updated['source_decision_ids']==['one']


@pytest.mark.parametrize('mode,label,fields',[('PICK','GOOD',{}),('PICK','BAD',{}),('ADVISE','GOOD',{'learnable':False}),('ADVISE','GOOD',{'conditions':[]})])
async def test_unlearnable_or_arbitrary_pick_never_creates_journal(tmp_path,mode,label,fields):
    learning=stack(tmp_path,[reflection(**fields)]);episode(learning,mode=mode,label=label)
    result=await learning.reflect('one');assert result['journal_action']=='NONE' and learning.journal.list()==[]


async def test_unknown_uses_no_model_and_records_none(tmp_path):
    learning=stack(tmp_path);episode(learning,label='UNKNOWN');result=await learning.reflect('one')
    assert not result['learnable'] and not learning.provider.calls and learning.history.get('one')['reflected']


async def test_repeated_no_difference_learns_decision_cost_not_option_preference(tmp_path):
    learning=stack(tmp_path,[reflection(statement='这类小选择以后优先直接 PICK，减少检索和追问',
        source_decision_ids=['one','two','three'])])
    for identity in ['one','two','three']:episode(learning,identity,mode='PICK',label='NO_DIFFERENCE')
    result=await learning.reflect('one');assert result['journal_action']=='CREATE'
    assert '减少检索' in learning.journal.list()[0]['statement']
    assert learning.journal.list()[0]['source_decision_ids']==['one','two','three']


@pytest.mark.parametrize('fields',[{'source_decision_ids':['fake']},{'target_journal_id':'missing','journal_action':'SUPPORT'}, {'principle_conflicts':['fake']}, {'decision_id':'fake'}])
async def test_forged_reflection_is_rejected_without_partial_journal(tmp_path,fields):
    learning=stack(tmp_path,[reflection(**fields)]);episode(learning)
    with pytest.raises(ValueError):await learning.reflect('one')
    assert not learning.journal.list() and not learning.journal.reflections() and not learning.history.get('one')['reflected']


async def test_provider_failure_can_retry_without_damaging_feedback(tmp_path):
    learning=stack(tmp_path,[ModelResponse(content='{bad'),reflection()]);row=episode(learning)
    with pytest.raises(ValueError):await learning.reflect('one')
    assert learning.history.get('one')['feedback']==row['feedback'] and not learning.journal.list()
    await learning.reflect('one');assert learning.journal.list()


async def test_feedback_changed_during_reflection_is_not_committed(tmp_path):
    learning=stack(tmp_path);episode(learning)
    async def generate(*args,**kwargs):
        learning.history.feedback('one',scope=SCOPE,outcome_label='BAD')
        return reflection()
    learning.provider.generate=generate
    with pytest.raises(ValueError,match='Feedback changed'):await learning.reflect('one')
    assert not learning.journal.reflections() and learning.history.get('one')['feedback']['label']=='BAD'


async def test_stale_journal_after_await_retries_without_overwriting_manual_edit(tmp_path):
    learning=stack(tmp_path);entry=seed(learning)
    episode(learning,journal_ids=[entry['id']])
    async def generate(*args,**kwargs):
        learning.journal.edit(entry['id'],{'statement':'用户手工调整'})
        return reflection('REFINE',target_journal_id=entry['id'])
    learning.provider.generate=generate
    with pytest.raises(ValueError,match='Journal changed'):await learning.reflect('one')
    assert learning.journal.get(entry['id'])['statement']=='用户手工调整'
    assert not learning.journal.reflections()


async def test_committed_reflection_recovers_history_marker_without_extra_model(tmp_path,monkeypatch):
    learning=stack(tmp_path,[reflection()]);episode(learning)
    original=learning.history.event
    monkeypatch.setattr(learning.history,'event',Mock(side_effect=OSError('history disk failure')))
    with pytest.raises(OSError):await learning.reflect('one')
    assert learning.journal.reflections() and learning.pending()
    monkeypatch.setattr(learning.history,'event',original)
    await learning.reflect('one');assert len(learning.provider.calls)==1 and not learning.pending()


async def test_secondary_file_failure_does_not_half_commit_journal(tmp_path,monkeypatch):
    import zhaoxi.decision.journal as module
    learning=stack(tmp_path,[reflection()]);episode(learning);original=module.append_row
    def append(path,row):
        if path.name=='decision_reflection.jsonl':raise OSError('sidecar')
        original(path,row)
    monkeypatch.setattr(module,'append_row',append)
    await learning.reflect('one')
    restored=DecisionJournalStore(learning.journal.directory)
    assert len(restored.list())==len(restored.reflections())==1 and restored.revisions()


async def test_repeated_conflicts_only_create_review_candidate(tmp_path):
    learning=stack(tmp_path);root=learning.principles.directory;root.mkdir()
    text=json.dumps({'id':'mainline','statement':'保护主线','source':{'type':'archive'}})
    (root/'mainline.json').write_text(text,encoding='utf-8')
    for identity in ['one','two']:
        episode(learning,identity,principle_ids=['mainline'])
        learning.provider.responses.clear()
        learning.provider.responses.append(reflection(decision_id=identity,principle_conflicts=['mainline']))
        await learning.reflect(identity)
    assert len(learning.journal.review_candidates())==1
    assert (root/'mainline.json').read_text(encoding='utf-8')==text
    assert all(r['status']=='CONFLICTED' for r in learning.journal.list())


def test_journal_manual_crud_provenance_and_gardening_guards(tmp_path):
    learning=stack(tmp_path);old=datetime.now(UTC)-timedelta(days=100)
    one=seed(learning,last_reviewed_at=old);locked=seed(learning,manual_state='LOCKED',last_reviewed_at=old)
    learning.journal.edit(one['id'],{'title':'新标题'});assert len(learning.journal.revisions(one['id']))==2
    with pytest.raises(ValueError):learning.journal.edit(one['id'],{'source_decision_ids':['forged']})
    learning.journal.garden();assert learning.journal.get(one['id'])['status']=='STALE'
    assert learning.journal.get(locked['id'])['status']=='UNCERTAIN'
    learning.journal.delete(one['id']);assert learning.journal.get(one['id']) is None
    assert learning.journal.revisions(one['id'])[0]['operation']=='DELETE'


def test_gardening_exact_merge_preserves_evidence_and_retires_old(tmp_path):
    learning=stack(tmp_path)
    seed(learning,source_decision_ids=['one']);seed(learning,source_decision_ids=['two'])
    changes=learning.journal.garden();assert changes and len(learning.journal.list())==1
    assert set(learning.journal.list()[0]['source_decision_ids'])=={'one','two'}
    seed(learning,statement='过时经验',last_reviewed_at=datetime.now(UTC)-timedelta(days=190))
    learning.journal.garden();assert any(r['status']=='RETIRED' for r in learning.journal.list(include_retired=True))


async def test_archive_whitelist_bounded_sources_and_no_escape(tmp_path):
    root=tmp_path/'archive';root.mkdir();(root/'user').mkdir()
    (root/'user'/'protocol.md').write_text(('注意力比小钱重要\n'*10000),encoding='utf-8')
    outside=tmp_path/'secret.md';outside.write_text('注意力 SECRET',encoding='utf-8')
    provider=DecisionPrincipleArchiveProvider(root,['user/protocol.md','../secret.md'])
    rows=await provider.retrieve('注意力',limit=2)
    assert len(rows)==2 and all(len(r['content'])<=1000 for r in rows)
    assert all('SECRET' not in r['content'] and r['ref'].startswith('archive:user/') for r in rows)


@pytest.mark.parametrize('policy', ['NEVER','PASSIVE','OPPORTUNISTIC','SCHEDULED'])
def test_followup_due_modes_feedback_and_expiry(tmp_path,policy):
    learning=stack(tmp_path);now=datetime.now(UTC)
    episode(learning,label=None,follow_up_policy=policy,follow_up_after=now-timedelta(hours=2))
    settings=Settings(_env_file=None);service=DecisionFollowUp(learning.history,settings)
    assert bool(service.candidates(now)) == (policy=='SCHEDULED')
    assert bool(service.candidates(now,opportunistic=True)) == (policy in {'OPPORTUNISTIC','SCHEDULED'})
    if policy in {'OPPORTUNISTIC','SCHEDULED'}:
        service.candidates(now+timedelta(days=60),opportunistic=True)
        assert learning.history.get('one')['follow_up_status']=='EXPIRED'
    learning.history.feedback('one',scope=SCOPE,outcome_label='GOOD')
    assert not service.candidates(now,opportunistic=True)


def test_followup_future_not_due_budget_and_min_interval(tmp_path):
    learning=stack(tmp_path);now=datetime.now(UTC)
    episode(learning,label=None,follow_up_policy='SCHEDULED',follow_up_after=now+timedelta(days=1))
    service=DecisionFollowUp(learning.history,Settings(_env_file=None,decision_follow_up_daily_limit=1))
    assert not service.candidates(now)
    learning.history.event('one','follow_up',scope=SCOPE,follow_up_status='ASKED',asked_at=now.isoformat())
    assert not service.budget_allowed(now+timedelta(minutes=1))
    assert service.budget_allowed(now+timedelta(days=1))


async def test_followup_policy_cooldown_presence_and_no_repeat(tmp_path):
    from zhaoxi.proactive.policy import PolicyState,InterruptPolicy
    from zhaoxi.proactive.sqlite import SQLiteProactiveStore
    from zhaoxi.proactive.notifications import InboxNotificationSink
    from zhaoxi.proactive.runtime import ProactiveRuntime
    learning=stack(tmp_path);now=datetime(2026,10,4,7,tzinfo=UTC)
    episode(learning,label=None,follow_up_policy='SCHEDULED',follow_up_after=now-timedelta(hours=2))
    settings=Settings(_env_file=None);service=DecisionFollowUp(learning.history,settings)
    store=SQLiteProactiveStore(tmp_path/'proactive.db')
    proactive=ProactiveRuntime(store,InboxNotificationSink(store),InterruptPolicy())
    state=PolicyState();state.interaction.interact(now-timedelta(minutes=10))
    runtime=SimpleNamespace(agent=SimpleNamespace(proactive=proactive,proactive_state=state),
        presence=lambda:SimpleNamespace(value='SEMI_ACTIVE'),_foreground_count=0)
    row=service.candidates(now)[0]
    runtime._foreground_count=1;assert not await service.ask(row,runtime,now)
    runtime._foreground_count=0
    state.quiet_until=now+timedelta(hours=1);assert not await service.ask(row,runtime,now)
    state.quiet_until=None
    deliveries=await service.ask(row,runtime,now);assert len(deliveries)==1
    assert not await service.ask(row,runtime,now+timedelta(days=1))
    assert learning.history.get('one')['follow_up_status']=='ASKED'
    assert 'decision #' not in deliveries[0].content


async def test_context_journal_user_principles_alias_real_receipts(tmp_path):
    from zhaoxi.decision.awareness import DecisionAwareness
    from zhaoxi.decision.context import ReadDecisionContext
    learning=stack(tmp_path);entry=seed(learning)
    learning.principles.directory.mkdir()
    (learning.principles.directory/'explicit.json').write_text(json.dumps({'id':'explicit','statement':'低精力保护主线',
        'source':{'type':'archive','path':'user/test.md'}}),encoding='utf-8')
    awareness=DecisionAwareness();awareness.journal=learning.journal;awareness.user_principles=learning.principles
    tool=ReadDecisionContext(awareness)
    result=await tool.run({'query':'低精力','sources':['user_principles','principles','decision_journal']})
    assert result.success and result.data['sources']['decision_journal'][0]['ref']=='decision_journal:'+entry['id']
    assert result.data['sources']['principles'][0]['statement']==result.data['sources']['user_principles'][0]['statement']


def test_activity_presence_defaults_and_backup_registry(tmp_path):
    from zhaoxi.internal_activity.runtime import InternalActivityRuntime
    from zhaoxi.bootstrap.storage import build_data_store_specs
    settings=Settings(_env_file=None)
    runtime=InternalActivityRuntime(SimpleNamespace(),settings,tmp_path/'activity.db')
    assert runtime.control.config('decision_follow_up')['daily_budget']==2
    assert runtime.control.config('decision_follow_up')['presence_policy']=={
        'ACTIVE':'AUTO','SEMI_ACTIVE':'AUTO','IDLE':'MANUAL_ONLY','AWAY':'DISABLED','SLEEP':'DISABLED'}
    assert runtime.control.config('decision_reflection')['presence_policy']['ACTIVE']=='MANUAL_ONLY'
    specs=build_data_store_specs(settings,archive_enabled=False)
    assert {'decision_journal','decision_reflection','decision_journal_revision','user_principles'} <= {s.name for s in specs}


async def test_dashboard_api_auth_feedback_journal_reflection_queue(tmp_path):
    from zhaoxi.core.agent import ZhaoxiAgent
    from zhaoxi.core.context import ContextBuilder
    from zhaoxi.tools.registry import ToolRegistry
    from zhaoxi.web.app import create_app
    learning=stack(tmp_path);episode(learning,label=None)
    agent=ZhaoxiAgent(provider=learning.provider,registry=ToolRegistry(),context_builder=ContextBuilder('朝汐'),decision_mode='agency')
    agent.decision_learning=learning;agent.decision_follow_up=DecisionFollowUp(learning.history,Settings(_env_file=None))
    agent.decision_awareness.history=learning.history;agent.decision_awareness.principle_archive=DecisionPrincipleArchiveProvider(tmp_path,[])
    app=create_app(agent=agent,settings=Settings(_env_file=None,perception_enabled=False),api_token='test')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://localhost') as client:
        assert (await client.get('/api/decision/journal')).status_code==401
        client.headers['X-Zhaoxi-Token']='test'
        assert (await client.get('/api/decision/history')).json()['items'][0]['schema_version']==3
        response=await client.post('/api/decision/history/one/feedback',json={'outcome_label':'MIXED','outcome_text':'开心但赶工'})
        assert response.status_code==200 and response.json()['receipt']['status']=='SUCCESS'
        assert (await client.post('/api/decision/history/one/reflect')).status_code==200
        assert not learning.provider.calls
        response=await client.post('/api/decision/journal',json={'title':'经验','statement':'临近 deadline 先看现实约束'})
        identity=response.json()['data']['id']
        assert (await client.patch('/api/decision/journal/'+identity,json={'manual_state':'LOCKED'})).status_code==200
        assert (await client.get('/api/decision/journal/'+identity)).json()['manual_state']=='LOCKED'
        assert (await client.patch('/api/decision/journal/'+identity,json={'source_decision_ids':['fake']})).status_code==422
        assert (await client.patch('/api/decision/journal/'+identity,json={'confidence':None})).status_code==422
        assert (await client.post('/api/decision/journal/'+identity+'/retire')).status_code==200
        assert (await client.delete('/api/decision/journal/'+identity)).status_code==200
        assert (await client.get('/api/decision/journal/'+identity)).status_code==404
        assert (await client.get('/api/decision/user-principles')).status_code==200

async def test_natural_feedback_same_reply_and_ambiguous_chat_does_not_bind(tmp_path):
    from test_decision_awareness import make_agent
    agent,provider=make_agent(tmp_path,[],fast=False)
    identity='previous'
    agent.decision_awareness.history.record(identity,DecisionAwarenessTrace(mode='ADVISE',agent_recommendation='出去活动'),
        '下午活动安排',scope=SCOPE)
    provider.responses.append(ModelResponse(content=json.dumps({'reply':'回来状态好多了就好。','awareness':{
        'mode':'NONE','feedback':{'decision_id':identity,'outcome_label':'GOOD','outcome_text':'出去以后状态挺好'}}},ensure_ascii=False)))
    response=await agent.run_direct('刚才那个出去活动的建议挺好，回来精神好多了。')
    assert response.content=='回来状态好多了就好。' and len(provider.calls)==1
    assert agent.decision_awareness.history.get(identity)['feedback']['label']=='GOOD'
    provider.responses.clear();provider.responses.append(ModelResponse(content=json.dumps({'reply':'嗯。','awareness':{'mode':'NONE'}})))
    old=agent.decision_awareness.history.get(identity)['feedback']
    await agent.run_direct('挺好。')
    assert agent.decision_awareness.history.get(identity)['feedback']==old


async def test_opportunistic_same_main_reply_marks_once_without_new_call(tmp_path):
    from test_decision_awareness import make_agent
    agent,provider=make_agent(tmp_path,[],fast=True)
    history=agent.decision_awareness.history
    history.record('previous',DecisionAwarenessTrace(mode='ADVISE',agent_recommendation='参加活动',
        follow_up_policy='OPPORTUNISTIC',follow_up_after=datetime.now(UTC)-timedelta(days=1)),
        '昨天下午去舞萌',scope=SCOPE)
    service=DecisionFollowUp(history,Settings(_env_file=None));agent.decision_awareness.follow_up=service
    provider.responses.append(ModelResponse(content=json.dumps({'reply':'昨天下午那轮后来怎么样？','awareness':{
        'mode':'NONE','follow_up_asked_id':'previous'}},ensure_ascii=False)))
    await agent.run_natural('我回来了。')
    assert history.get('previous')['follow_up_status']=='ASKED' and len(provider.calls)==1
    assert not service.candidates(scope=SCOPE,opportunistic=True)


def test_history_incremental_projection_survives_replacement_and_returns_old_ids(tmp_path):
    learning=stack(tmp_path);episode(learning,'one');episode(learning,'two')
    assert learning.history.get('one')['feedback']['label']=='GOOD'
    path=learning.history.directory/'choice_history.jsonl'
    text=path.read_text(encoding='utf-8');path.write_text(text.replace('GOOD','BAD'),encoding='utf-8')
    assert learning.history.get('one')['feedback']['label']=='BAD'
    learning.history.feedback('one',scope=SCOPE,outcome_label='NEUTRAL')
    assert learning.history.get('two')['feedback']['label']=='BAD'
    assert ChoiceHistory(learning.history.directory).get('one')['feedback']['label']=='NEUTRAL'

async def test_source_fragment_is_original_whitelisted_user_section(tmp_path):
    root=tmp_path/'archive';(root/'user').mkdir(parents=True)
    (root/'user'/'protocol.md').write_text('# 决策协议\n## L0：自动决策\n低风险直接处理\n## L1：默认建议\n保持方向\n',encoding='utf-8')
    provider=DecisionPrincipleArchiveProvider(root,['user/protocol.md'])
    result=provider.source_fragment({'statement':'低风险直接处理','source':{
        'path':'data/archive/user/protocol.md','version':'1.0','ref':'2/L0'}})
    assert result[0]['line']==2 and result[0]['authority']=='user_archive'
    assert '低风险直接处理' in result[0]['content'] and 'L1' not in result[0]['content']
    assert not provider.source_fragment({'statement':'secret','source':{'path':'../secret.md','ref':'L0'}})

def test_opportunistic_followup_honors_disabled_control_and_sleep(tmp_path):
    from zhaoxi.internal_activity.runtime import InternalActivityRuntime
    learning=stack(tmp_path);settings=Settings(_env_file=None)
    runtime=InternalActivityRuntime(SimpleNamespace(),settings,tmp_path/'activity.db')
    service=DecisionFollowUp(learning.history,settings);service.runtime=runtime
    runtime.presence=lambda:SimpleNamespace(value='SEMI_ACTIVE')
    assert service.policy_allowed()
    runtime.control.update('configs',{'enabled':False},name='decision_follow_up')
    assert not service.policy_allowed()
    runtime.control.update('configs',{},name='decision_follow_up',reset=True)
    runtime.presence=lambda:SimpleNamespace(value='SLEEP')
    assert not service.policy_allowed(manual=True)
    runtime.presence=lambda:SimpleNamespace(value='IDLE')
    assert service.policy_allowed(manual=True) and not service.policy_allowed()
    runtime.control.update('configs',{'daily_budget':0},name='decision_follow_up')
    assert not service.budget_allowed()

def test_result_only_feedback_preserves_actual_final_choice_and_override(tmp_path):
    learning=stack(tmp_path);episode(learning,label=None)
    learning.history.feedback('one','继续项目',scope=SCOPE,overridden=True)
    learning.history.feedback('one',scope=SCOPE,outcome_label='BAD',outcome_text='一下午完全没效率')
    row=learning.history.get('one')
    assert row['user_final_choice']=='继续项目' and row['overridden']
    assert row['suggestion']=='出去活动'


def test_background_feedback_is_not_lost_outside_recent_history_page(tmp_path):
    learning=stack(tmp_path);episode(learning)
    assert learning.pending()[0]['decision_id']=='one'
    learning.history.list=Mock(return_value=[])
    assert learning.pending()[0]['decision_id']=='one'
