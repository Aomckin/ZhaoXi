"""Explicit live acceptance: configured provider, synthetic isolated decision data."""
import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import time
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests'));sys.path.insert(0,str(ROOT/'tests/decision'))
from test_decision_awareness import make_agent
from decision_v146_live_acceptance import Counted
from zhaoxi.bootstrap.models import build_model_runtime
from zhaoxi.config.settings import Settings
from zhaoxi.decision.models import DecisionAwarenessTrace
from zhaoxi.decision.journal import DecisionJournalStore
from zhaoxi.decision.learning import DecisionLearning
from zhaoxi.decision.user_principles import UserPrincipleStore
from zhaoxi.decision.learning_models import DecisionJournalEntry
from zhaoxi.reliability.retry import provider_budget_scope

async def run():
    settings=Settings();settings.retry_max_attempts=1;settings.request_timeout_seconds=60
    run_id=uuid4().hex;rows=[]
    async def case(name, action):
        start=time.perf_counter()
        try:
            with provider_budget_scope(4):
                row=await asyncio.wait_for(action(),120)
        except Exception as exc:
            row={'passed':False,'error':type(exc).__name__,'error_code':getattr(exc,'code',None)}
        row.update(case=name,elapsed_ms=round((time.perf_counter()-start)*1000));rows.append(row)
        print(json.dumps(row,ensure_ascii=False),flush=True)
    def new(name):
        path=ROOT/'.zhaoxi/v147-live-fixtures'/run_id/name
        agent,_=make_agent(path,[],fast=True);provider=Counted(build_model_runtime(settings));agent.provider=provider
        return agent,provider,path
    async def pick():
        agent,p,path=new('pick');result=await agent.run_natural('两根一块钱的笔，黑壳白壳功能一样，选哪根？')
        row=agent.decision_awareness.history.list()[0]
        return {'passed':p.calls==1 and row['mode']=='PICK','model_calls':p.calls,'mode':row['mode'],'reply':result.content}
    await case('FAST PICK',pick)
    async def feedback():
        agent,p,path=new('feedback');history=agent.decision_awareness.history
        history.record('yesterday',DecisionAwarenessTrace(mode='ADVISE',decision_kind='NEW',decision_question='低精力下午应外出散步还是继续项目？',agent_recommendation='出去散步'),
            '昨天下午低精力且没有紧急 deadline，在寝室低效很久，要出门还是继续项目',scope='owner:desktop:local')
        result=await agent.run_direct('昨天你让我出去散步，我去了，回来精神好多了，这个建议挺好。')
        row=history.get('yesterday')
        return {'passed':row['feedback'] is not None and row['feedback']['label']=='GOOD','model_calls':p.calls,
            'feedback':row['feedback'],'reply':result.content,'raw_awareness':p.last_awareness}
    await case('natural outcome feedback',feedback)
    async def ambiguous():
        agent,p,path=new('ambiguous');history=agent.decision_awareness.history
        for identity in ['lunch','pen']:
            history.record(identity,DecisionAwarenessTrace(mode='PICK',decision_kind='NEW',decision_question='当前备选商品应选哪一个？',agent_recommendation='第一个'),identity,scope='owner:desktop:local')
        result=await agent.run_direct('今天挺开心的。')
        return {'passed':all(r['feedback'] is None for r in history.list()),'model_calls':p.calls,'reply':result.content}
    await case('unbound casual feedback',ambiguous)
    async def reflect_good():
        agent,p,path=new('reflect');history=agent.decision_awareness.history;journal=DecisionJournalStore(path/'journal')
        entry=journal.create(DecisionJournalEntry(title='低精力时换个环境',statement='没有紧急 deadline 时，低精力且低效很久可以考虑出去活动',
            conditions=['无紧急 deadline','低精力且低效很久'],confidence=.6).model_dump(mode='json'))
        history.record('one',DecisionAwarenessTrace(mode='ADVISE',decision_kind='NEW',decision_question='低精力下午应外出散步还是继续项目？',agent_recommendation='出去散步',journal_ids=[entry['id']]),
            '低精力且没有紧急 deadline，在寝室低效很久，出门还是继续项目',scope='owner:desktop:local')
        history.feedback('one',scope='owner:desktop:local',outcome_label='GOOD',outcome_text='出门回来精神好多了，晚上项目也顺利推进')
        learning=DecisionLearning(history,journal,UserPrincipleStore(path/'principles'),p);result=await learning.reflect('one')
        return {'passed':result['journal_action'] in {'SUPPORT','REFINE'} and result['target_journal_id']==entry['id'],
            'model_calls':p.calls,'reflection':result,'journal':journal.get(entry['id'])}
    await case('GOOD reflection',reflect_good)
    async def no_difference():
        agent,p,path=new('no-difference');history=agent.decision_awareness.history;journal=DecisionJournalStore(path/'journal')
        for identity in ['one','two','three']:
            history.record(identity,DecisionAwarenessTrace(mode='PICK',decision_kind='NEW',decision_question='本次购买应选哪种外壳的笔？',agent_recommendation='黑壳笔'),
                '两根一块钱的笔，黑壳白壳功能一样，选哪根',scope='owner:desktop:local')
            history.feedback(identity,scope='owner:desktop:local',outcome_label='NO_DIFFERENCE',outcome_text='黑壳白壳写起来都一样，真不用纠结')
        learning=DecisionLearning(history,journal,UserPrincipleStore(path/'principles'),p);result=await learning.reflect('one')
        return {'passed':result['journal_action']=='CREATE' and len(journal.list())==1,
            'model_calls':p.calls,'reflection':result,'journal':journal.list()}
    await case('repeated NO_DIFFERENCE reflection',no_difference)
    destination=ROOT/'docs/v1.4.x/evidence/decision_v147_live_acceptance.json'
    evidence={'environment':'configured real provider; synthetic contexts; isolated stores; no production tools',
        'run_id':run_id,'call_count_unit':'generate calls, not transport attempts','cases':rows}
    if destination.exists():
        previous=json.loads(destination.read_text(encoding='utf-8'));evidence['prior_attempts']=[*previous.get('prior_attempts',[]),{'cases':previous['cases']}]
    destination.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return int(not all(r['passed'] for r in rows))

if __name__=='__main__':raise SystemExit(asyncio.run(run()))
