import asyncio
from dataclasses import replace
import pytest
from test_presence_v144 import runtime
from zhaoxi.internal_activity.receipt import build_receipt
from zhaoxi.internal_activity.models import ActivityResult

@pytest.mark.parametrize("status",["SUCCESS","NO_CHANGE","SKIPPED","BLOCKED","FAILED","CANCELLED"])
def test_all_statuses_have_human_feedback(tmp_path,status):
    r=runtime(tmp_path)
    receipt=build_receipt(r.registry.get("cognition_gardening"),status=status).diagnostics()
    assert receipt["summary"] and receipt["status_label"]
    assert receipt["status"]==status
    assert receipt["raw_payload"]=={}
    assert not r.agent.provider.calls

async def test_running_and_finished_sse_share_id_and_history_survives_restart(tmp_path):
    r=runtime(tmp_path)
    events=[];r.publish_status=events.append
    receipt=await r.run_manual("cognition_gardening")
    started=next(e for e in events if e["type"]=="activity_started")
    finished=next(e for e in events if e["type"]=="activity_finished")
    assert started["receipt"]["action_id"]==finished["receipt"]["action_id"]==receipt["action_id"]
    assert receipt["status"]=="NO_CHANGE"
    assert runtime(tmp_path).history()["items"][0]["action_id"]==receipt["action_id"]
    assert not r.agent.provider.calls

async def test_preemption_has_cancelled_receipt_and_error_has_failed_receipt(tmp_path):
    r=runtime(tmp_path)
    name="cognition_gardening";started=asyncio.Event()
    async def slow(*_):
        started.set();await asyncio.sleep(60)
    r.registry._specs[name]=replace(r.registry.get(name),handler=slow)
    task=asyncio.create_task(r.run_manual(name))
    await asyncio.wait_for(started.wait(),1)
    r.foreground_enter()
    receipt=await asyncio.wait_for(task,1)
    assert receipt["status"]=="CANCELLED"
    r.foreground_exit()
    async def fail(*_):raise ValueError("broken")
    r.registry._specs[name]=replace(r.registry.get(name),handler=fail)
    receipt=await r.run_manual(name)
    assert receipt["status"]=="FAILED" and receipt["error"]["stage"]=="execution"
    assert r.current_activity is None

async def test_unconfirmed_social_write_is_blocked_without_provider(tmp_path):
    r=runtime(tmp_path)
    receipt=await r.run_manual("social_wander")
    assert receipt["status"]=="BLOCKED"
    assert not receipt["side_effects"]["external_write"]
    assert not r.agent.provider.calls
