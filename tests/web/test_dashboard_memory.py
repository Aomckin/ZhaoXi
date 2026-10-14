from fastapi.testclient import TestClient
from dashboard_fixture import dashboard_core
from zhaoxi.web.app import create_app
from zhaoxi.interfaces.models import UnifiedResponse
from zhaoxi.memory.models import MemoryCreate, MemoryCluster
from zhaoxi.memory.service import MemoryService
from zhaoxi.memory.sqlite import SQLiteMemoryRepository
import asyncio


def test_memory_overview_uses_local_request_not_qq_or_inspector(tmp_path):
    core,settings=dashboard_core(tmp_path)
    core.memory_service=MemoryService(SQLiteMemoryRepository(tmp_path/'memory.db'))
    asyncio.run(core.memory_service.remember(MemoryCreate(kind='episodic',content='Orion project blue',source='user')))
    asyncio.run(core.memory_service.repository.save_cluster(MemoryCluster(topic='Orion project',member_count=1)))
    app=create_app(agent=core,settings=settings,api_token='memory-test')
    gateway=app.state.adapter.gateway
    local={'memory_candidates':[{'id':'local-fact','content':'local returned fact'}],
           'timeline':[{'event_type':'memory_search_started','metadata':{'mode':'preload'}}],
           'tool_calls':[{'tool_name':'search_memories'}]}
    gateway._responses['local-request']=UnifiedResponse(request_id='local-request',session_id='local',activity={'runtime_metrics':local})
    gateway._responses['qq-request']=UnifiedResponse(request_id='qq-request',session_id='qq:group:123',activity={'runtime_metrics':{'memory_candidates':[{'id':'qq-fact'}]}})
    core.last_action_trace={'request_id':'qq-request','runtime_metrics':{'memory_candidates':[{'id':'qq-fact'}]}}
    core.memory_service.last_retrieval={'selected':[{'memory_id':'inspector-fact'}]}
    with TestClient(app) as client:
        assert client.get('/api/dashboard/memory').status_code==401
        data=client.get('/api/dashboard/memory',headers={'X-Zhaoxi-Token':'memory-test'}).json()
    assert data['diagnostics']['total']==1 and data['clusters']
    assert all('centroid_embedding' not in c for c in data['clusters'])
    assert data['retrieval']['request_id']=='local-request'
    assert data['retrieval']['candidates']==local['memory_candidates']
    assert data['retrieval']['preload_count']==data['retrieval']['tool_search_count']==1


def test_memory_overview_does_not_substitute_old_recall_for_empty_turn(tmp_path):
    core,settings=dashboard_core(tmp_path)
    core.memory_service=MemoryService(SQLiteMemoryRepository(tmp_path/'memory.db'))
    app=create_app(agent=core,settings=settings,api_token='memory-test')
    headers={'X-Zhaoxi-Token':'memory-test'}
    with TestClient(app) as client:
        assert client.get('/api/dashboard/memory',headers=headers).json()['retrieval'] is None
        gateway=app.state.adapter.gateway
        gateway._responses['old']=UnifiedResponse(request_id='old',activity={'runtime_metrics':{'memory_candidates':[{'id':'old-fact'}]}})
        gateway._responses['new']=UnifiedResponse(request_id='new',activity={'runtime_metrics':{'memory_candidates':[]}})
        data=client.get('/api/dashboard/memory',headers=headers).json()
        assert data['retrieval']['request_id']=='new' and not data['retrieval']['candidates']
        core.memory_service=None
        assert client.get('/api/dashboard/memory',headers=headers).status_code==409