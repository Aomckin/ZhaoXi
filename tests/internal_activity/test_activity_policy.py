from types import SimpleNamespace
from datetime import UTC, datetime
import pytest
from test_presence_v144 import runtime
from zhaoxi.proactive.interaction import Interaction, InteractionState
from zhaoxi.internal_activity.models import ActivityResult

@pytest.mark.parametrize("presence",list(InteractionState))
@pytest.mark.parametrize("policy",["AUTO","MANUAL_ONLY","DISABLED"])
@pytest.mark.parametrize("manual",[False,True])
async def test_policy_matrix(tmp_path,presence,policy,manual):
    r=runtime(tmp_path)
    i=Interaction();i.force_debug_state(presence,datetime.now(UTC))
    r.agent.proactive_state=SimpleNamespace(interaction=i,interacting=False)
    name="memory_reminiscence"
    spec=r.registry.get(name)
    from dataclasses import replace
    async def due(*_):return "test","local"
    async def handler(*_):return ActivityResult(changed=True,status="UPDATE")
    r.registry._specs[name]=replace(spec,candidate=due,handler=handler)
    config=r.control.config(name)
    config["presence_policy"]={str(p):policy for p in InteractionState}
    r.control.update("configs",config,name=name)
    await r.run_tick(force=name if manual else None,manual=manual)
    allowed=policy=="AUTO" or manual and policy=="MANUAL_ONLY"
    assert (name in r.last_selected)==allowed

async def test_manual_budget_and_global_disable_are_not_bypassed(tmp_path):
    r=runtime(tmp_path)
    r.control.update("activity",{"max_activities_per_tick":0})
    receipt=await r.run_manual("cognition_gardening")
    assert receipt["status"]=="SKIPPED" and "预算" in receipt["summary"]
    r.control.update("activity",{"enabled":False})
    receipt=await r.run_manual("cognition_gardening")
    assert receipt["status"]=="BLOCKED"

async def test_daily_llm_cap_and_config_persistence(tmp_path):
    r=runtime(tmp_path)
    r.control.update("activity",{"daily_llm_budget":0})
    receipt=await r.run_manual("fast_digest")
    assert receipt["status"]=="SKIPPED"
    config=r.control.config("memory_reminiscence")
    config["presence_policy"]["ACTIVE"]="MANUAL_ONLY"
    r.control.update("configs",config,name="memory_reminiscence")
    assert runtime(tmp_path).control.config("memory_reminiscence")["presence_policy"]["ACTIVE"]=="MANUAL_ONLY"
