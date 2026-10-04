"""Isolated Decision Learning browser fixture; no production stores or model."""
from datetime import UTC, datetime, timedelta
import json
from uuid import uuid4
from pathlib import Path
import uvicorn
from dashboard_fixture import dashboard_core
from zhaoxi.decision.awareness import DecisionAwareness
from zhaoxi.decision.history import ChoiceHistory
from zhaoxi.decision.models import DecisionAwarenessTrace
from zhaoxi.decision.journal import DecisionJournalStore
from zhaoxi.decision.learning import DecisionLearning
from zhaoxi.decision.follow_up import DecisionFollowUp
from zhaoxi.decision.user_principles import UserPrincipleStore, DecisionPrincipleArchiveProvider
from zhaoxi.models.types import ModelResponse
from zhaoxi.web.app import create_app

class Provider:
    async def generate(self,*args,**kwargs):
        data=json.loads(args[0][-1].content)
        return ModelResponse(content=json.dumps({'decision_id':data['decision']['decision_id'],
            'learnable':True,'summary':'外出后状态改善，但临近 deadline 需要留意',
            'journal_action':'CREATE','title':'换个环境','statement':'低精力时可考虑换个环境',
            'conditions':['没有紧急 deadline'],'exceptions':['临近交付'],
            'reason':'真实反馈支持一次暂时判断，不能当永久规则','confidence_delta':.05},ensure_ascii=False))

if __name__=='__main__':
    path=Path('.zhaoxi/v147-browser-fixture')/uuid4().hex;path.mkdir(parents=True,exist_ok=True)
    core,settings=dashboard_core(path);settings.dev_browser_ui=False
    core.provider=Provider();history=ChoiceHistory(path/'decisions');journal=DecisionJournalStore(path/'decisions')
    if not history.get('activity'):
        history.record('activity',DecisionAwarenessTrace(mode='ADVISE',agent_recommendation='出去活动',
            follow_up_policy='SCHEDULED',follow_up_after=datetime.now(UTC)-timedelta(days=1)),
            '下午去舞萌还是继续项目',scope='owner:desktop:local')
    principles=UserPrincipleStore('data/decisions/user_principles')
    core.decision_awareness=DecisionAwareness(history=history)
    core.decision_awareness.journal=journal;core.decision_awareness.user_principles=principles
    core.decision_awareness.principle_archive=DecisionPrincipleArchiveProvider('data/archive',settings.decision_principle_archive_paths)
    core.decision_learning=DecisionLearning(history,journal,principles,core.provider)
    core.decision_follow_up=DecisionFollowUp(history,settings)
    core.internal_activity.control.update('presence',{'heartbeat_enabled':False})
    uvicorn.run(create_app(agent=core,settings=settings,api_token='v147-browser-test'),host='127.0.0.1',port=18767)
