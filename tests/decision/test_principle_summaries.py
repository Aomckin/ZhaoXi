"""Archive-grounded model summary writes and original-first retrieval."""
import json
from types import SimpleNamespace
import httpx
import pytest
from conftest import FakeProvider
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.decision.awareness import DecisionAwareness
from zhaoxi.decision.context import ReadDecisionContext
from zhaoxi.decision.principle_tools import PrincipleWrite, WriteUserPrinciple, save_principle
from zhaoxi.decision.user_principles import UserPrincipleStore, DecisionPrincipleArchiveProvider
from zhaoxi.models.types import ModelResponse, ToolCall
from zhaoxi.tools.registry import ToolRegistry


def setup(tmp_path):
    root = tmp_path / 'archive'
    (root / 'user').mkdir(parents=True)
    (root / 'user' / 'new-v2.md').write_text('# 新准则\n低精力时保护主线，临近交付先完成项目。\n', encoding='utf-8')
    (root / 'zhaoxi').mkdir()
    (root / 'zhaoxi' / 'agent.md').write_text('低精力时保护主线 '*100, encoding='utf-8')
    archive = DecisionPrincipleArchiveProvider(root, ['user/old-v1.md','zhaoxi/agent.md'])
    awareness = DecisionAwareness()
    awareness.principle_archive = archive
    awareness.user_principles = UserPrincipleStore(tmp_path / 'principles', archive)
    return awareness


def arguments(**updates):
    return {'id':'protect-mainline','statement':'低精力时先照顾项目主线，临近交付优先完成项目。',
            'tags':['低精力','主线'], 'source_ref':'archive:user/new-v2.md:L1',
            'source_quote':'低精力时保护主线，临近交付先完成项目。', **updates}


async def test_model_writes_revision_and_restart_projects_latest(tmp_path):
    awareness=setup(tmp_path);tool=WriteUserPrinciple(awareness)
    result=await tool.run(arguments());assert result.success
    assert result.data['origin']=='zhaoxi_summary'
    assert result.data['source']['quote']==arguments()['source_quote']
    path=awareness.user_principles.directory/'protect-mainline.json'
    assert json.loads(path.read_text(encoding='utf-8'))['origin']=='zhaoxi_summary'
    result=await tool.run(arguments(statement='临近交付时优先完成项目，平时再按精力调整。'))
    assert result.success
    # Per-entry JSON is a repairable index: the committed revision survives cache loss.
    path.unlink()
    restored=UserPrincipleStore(awareness.user_principles.directory)
    assert restored.list()[0]['statement']==result.data['statement']
    assert len(restored.revisions('protect-mainline'))==2
    assert len(awareness.principle_archive.fragments('低精力',user_only=True))==1


async def test_identical_retry_does_not_add_revision(tmp_path):
    awareness=setup(tmp_path);tool=WriteUserPrinciple(awareness)
    first=await tool.run(arguments());second=await tool.run(arguments())
    assert first.success and second.success
    assert len(awareness.user_principles.revisions('protect-mainline'))==1


@pytest.mark.parametrize('updates',[
    {'source_ref':'archive:user/../../outside.md:L1'},
    {'source_ref':'archive:zhaoxi/agent.md:L1'},
    {'source_ref':'archive:user/new-v2.md:L999'},
    {'source_quote':'这是用户没有说过的偏好'},
    {'id':'../outside'},
])
async def test_invalid_evidence_cannot_write(tmp_path,updates):
    awareness=setup(tmp_path)
    result=await WriteUserPrinciple(awareness).run(arguments(**updates))
    assert not result.success and not awareness.user_principles.list()


async def test_originals_precede_summary_and_new_files_are_found(tmp_path):
    awareness=setup(tmp_path)
    await WriteUserPrinciple(awareness).run(arguments())
    result=await ReadDecisionContext(awareness).run({'query':'低精力保护主线','sources':['user_principles','user_archive'],'limit':2})
    values=result.data['sources']['user_principles']
    assert values[0]['authority']=='user_archive' and values[0]['path']=='user/new-v2.md'
    assert values[1]['authority']=='summary_index_not_user_quote'
    assert all(r['authority']=='user_archive' for r in result.data['sources']['user_archive'])
    values=(await ReadDecisionContext(awareness).run({'query':'低精力','sources':['principles'],'limit':1})).data['sources']['principles']
    assert values[0]['authority']=='user_archive'
    (awareness.principle_archive.directory/'user'/'another.txt').write_text('低精力请先休息。',encoding='utf-8')
    assert any(r['path']=='user/another.txt' for r in awareness.principle_archive.fragments('低精力',user_only=True))


async def test_changed_original_is_reread_and_old_summary_is_not_used(tmp_path):
    awareness=setup(tmp_path)
    result=await WriteUserPrinciple(awareness).run(arguments())
    original=awareness.principle_archive.directory/'user'/'new-v2.md'
    original.write_text('# 新准则\n低精力时优先睡觉，不强行继续项目。\n',encoding='utf-8')
    assert awareness.principle_archive.source_status(result.data)=='changed'
    values=(await ReadDecisionContext(awareness).run({'query':'低精力','sources':['user_principles']})).data['sources']['user_principles']
    assert all(r['authority']=='user_archive' for r in values)
    assert '优先睡觉' in values[0]['content']


async def test_public_turn_cannot_write(tmp_path):
    from zhaoxi.cognitive_stream.models import CognitiveEvent
    from zhaoxi.cognitive_stream.turn import CognitiveTurnContext,set_current_turn,reset_current_turn
    awareness=setup(tmp_path)
    event=CognitiveEvent(event_type='USER_MESSAGE',source='desktop',actor_role='OWNER',content='资料',privacy_level='PUBLIC')
    token=set_current_turn(CognitiveTurnContext(trigger_event=event,audience='public'))
    try:
        assert not (await WriteUserPrinciple(awareness).run(arguments())).success
    finally:
        reset_current_turn(token)
    assert not awareness.user_principles.list()


async def test_main_model_tool_chain_reads_then_saves_without_extra_summarizer(tmp_path):
    awareness=setup(tmp_path)
    provider=FakeProvider([
        ModelResponse(tool_calls=[ToolCall(id='read',name='read_decision_context',arguments={'query':'低精力','sources':['user_archive']})]),
        ModelResponse(tool_calls=[ToolCall(id='write',name='write_user_principle',arguments=arguments())]),
        ModelResponse(content=json.dumps({'reply':'已经整理摘要并保留原文依据。','awareness':{'mode':'NONE'}},ensure_ascii=False)),
    ])
    registry=ToolRegistry()
    agent=ZhaoxiAgent(provider=provider,registry=registry,context_builder=ContextBuilder('朝汐'),decision_mode='agency')
    agent.decision_awareness.user_principles=awareness.user_principles
    agent.decision_awareness.principle_archive=awareness.principle_archive
    registry.register(WriteUserPrinciple(agent.decision_awareness))
    result=await agent.run('读取用户决策资料，把低精力原则整理到准则摘要索引。')
    assert '已经整理' in result.content
    assert len(provider.calls)==3 and awareness.user_principles.list()[0]['origin']=='zhaoxi_summary'
    assert any(m.name=='read_decision_context' for m in provider.calls[1])


async def test_authenticated_dashboard_save_and_revisions(tmp_path):
    from zhaoxi.config.settings import Settings
    from zhaoxi.web.app import create_app
    awareness=setup(tmp_path)
    core=ZhaoxiAgent(provider=FakeProvider([ModelResponse(content='ok')]),registry=ToolRegistry(),context_builder=ContextBuilder('朝汐'),decision_mode='agency')
    core.decision_awareness.user_principles=awareness.user_principles
    core.decision_awareness.principle_archive=awareness.principle_archive
    core.decision_learning=SimpleNamespace(principles=awareness.user_principles,history=SimpleNamespace(list=lambda **kw: []))
    app=create_app(agent=core,settings=Settings(_env_file=None,perception_enabled=False),api_token='fixture')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://localhost') as client:
        assert (await client.post('/api/decision/user-principles',json=arguments())).status_code==401
        client.headers['X-Zhaoxi-Token']='fixture'
        assert (await client.post('/api/decision/user-principles',json=arguments(source_quote='虚构'))).status_code==422
        saved=await client.post('/api/decision/user-principles',json=arguments())
        assert saved.status_code==200 and saved.json()['data']['origin']=='owner'
        listed=(await client.get('/api/decision/user-principles')).json()
        assert listed['items'][0]['source_status']=='current'
        revisions=(await client.get('/api/decision/user-principles/protect-mainline/revisions')).json()
        assert len(revisions['items'])==1


async def test_missing_original_does_not_fall_back_to_other_documents(tmp_path):
    awareness=setup(tmp_path)
    result=await WriteUserPrinciple(awareness).run(arguments())
    (awareness.principle_archive.directory/'user'/'new-v2.md').unlink()
    assert awareness.principle_archive.source_status(result.data)=='missing'
    values=(await ReadDecisionContext(awareness).run({'query':'低精力','sources':['user_principles']})).data['sources']['user_principles']
    assert values==[]


def test_user_archive_reads_do_not_label_parent_path_as_user_data(tmp_path):
    awareness=setup(tmp_path)
    awareness.principle_archive.paths=('user/../zhaoxi/agent.md',)
    values=awareness.principle_archive.fragments('低精力',user_only=True)
    assert all(v['path'].startswith('user/') and 'agent.md' not in v['path'] for v in values)


async def test_missing_source_is_removed_from_active_index_and_recovers(tmp_path):
    awareness = setup(tmp_path)
    assert (await WriteUserPrinciple(awareness).run(arguments())).success
    path = tmp_path / 'archive/user/new-v2.md'
    original = path.read_text(encoding='utf-8')
    path.unlink()
    row = awareness.user_principles.list()[0]
    assert row['source_status'] == 'missing' and row['effective_status'] == 'needs_update'
    assert awareness.user_principles.retrieve('低精力') == []
    path.write_text(original, encoding='utf-8')
    assert awareness.user_principles.list()[0]['effective_status'] == 'active'
    assert awareness.user_principles.retrieve('低精力')
