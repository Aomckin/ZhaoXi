import asyncio
import json
import sqlite3
import pytest
from zhaoxi.interfaces.maintenance import PostTurnMaintenanceQueue


@pytest.mark.asyncio
async def test_named_plan_survives_reorder_and_independent_failure(tmp_path):
    path = tmp_path/'q.db'
    seen = []
    async def handle(payload,name):
        seen.append(name)
        if name=='memory': raise ValueError('failed')
        return {'ok':True}
    q = PostTurnMaintenanceQueue(path,handle,phases=('memory','cognition','reflection'),foreground_busy=lambda:True)
    q.enqueue('a',{})
    await q.shutdown(0)
    q.db.close()
    q = PostTurnMaintenanceQueue(path,handle,phases=('reflection','cognition','memory'))
    q.start(); await q.worker
    assert seen==['memory','cognition','reflection']
    assert q.diagnostics()[0]['status']=='partial_failed'
    assert q.diagnostics()[0]['phases']==['memory','cognition','reflection']


@pytest.mark.asyncio
async def test_legacy_integer_checkpoint_does_not_replay_completed_memory(tmp_path):
    path=tmp_path/'q.db'
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE maintenance(id TEXT PRIMARY KEY,payload TEXT NOT NULL,phase INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL,error TEXT,duration_ms REAL NOT NULL DEFAULT 0)")
        db.execute("INSERT INTO maintenance(id,payload,phase,status) VALUES('a','{}',1,'queued')")
    seen=[]
    async def handle(payload,name):seen.append(name)
    q=PostTurnMaintenanceQueue(path,handle)
    q.start();await q.worker
    assert seen==['current_cognition']
    assert q.diagnostics()[0]['metrics']['auto_memory']['legacy_checkpoint']


@pytest.mark.asyncio
async def test_owner_priority_batch_freeze_capacity_and_request_dedup(tmp_path):
    seen=[]
    async def handle(payload,name):seen.append((payload,name))
    q=PostTurnMaintenanceQueue(tmp_path/'q.db',handle,phases=('memory',),foreground_busy=lambda:True,batch_delay=0,limit=3)
    for i in range(3):
        q.enqueue(str(i),{'trigger':{'event_id':str(i)},'messages':[{'message_id':str(i),'content':str(i)}]},batch_key='qq:owner',priority=5,batch_limit=2)
    q.enqueue('owner',{'request_id':'owner'},priority=10)
    q.enqueue('owner',{'request_id':'duplicate'},priority=10)
    assert q.db.execute("SELECT count(*) FROM maintenance WHERE status='queued'").fetchone()[0]==3
    q.foreground_busy=lambda:False
    await q.worker
    assert seen[0][0]['request_id']=='owner'
    assert [e['event_id'] for e in seen[1][0]['triggers']]==['0','1']
    assert len(seen)==3
    assert {d['id']:d['status'] for d in q.diagnostics()}['1']=='coalesced'
