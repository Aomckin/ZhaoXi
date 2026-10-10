"""Isolated browser fixture for archive-grounded summary editing."""
import asyncio
from pathlib import Path
from uuid import uuid4
import uvicorn
from dashboard_fixture import dashboard_core
from zhaoxi.decision.history import ChoiceHistory
from zhaoxi.decision.awareness import DecisionAwareness
from zhaoxi.decision.journal import DecisionJournalStore
from zhaoxi.decision.learning import DecisionLearning
from zhaoxi.decision.principle_tools import WriteUserPrinciple
from zhaoxi.decision.user_principles import UserPrincipleStore, DecisionPrincipleArchiveProvider
from zhaoxi.web.app import create_app

if __name__=='__main__':
    path=Path('.zhaoxi/principle-summary-browser')/uuid4().hex
    (path/'archive/user').mkdir(parents=True)
    (path/'archive/user/new-v2.md').write_text('# 决策准则\n低精力时保护项目主线，临近交付先完成项目。\n',encoding='utf-8')
    core,settings=dashboard_core(path)
    awareness=core.decision_awareness=DecisionAwareness()
    awareness.principle_archive=DecisionPrincipleArchiveProvider(path/'archive',[])
    awareness.user_principles=UserPrincipleStore(path/'principles',awareness.principle_archive)
    core.decision_learning=DecisionLearning(ChoiceHistory(path/'decisions'),DecisionJournalStore(path/'decisions'),awareness.user_principles,core.provider)
    core.internal_activity.control.update('presence',{'heartbeat_enabled':False})
    result=asyncio.run(WriteUserPrinciple(awareness).run({'id':'mainline','statement':'低精力时先保护主线。',
        'source_ref':'archive:user/new-v2.md:L1','source_quote':'低精力时保护项目主线，临近交付先完成项目。'}))
    assert result.success
    uvicorn.run(create_app(agent=core,settings=settings),host='127.0.0.1',port=18769)
