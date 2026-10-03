from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import pytest
from zhaoxi.proactive.interaction import Interaction, InteractionState
from test_presence_v144 import runtime

NOW = datetime(2026,10,3,tzinfo=UTC)
def test_input_transition_refresh_and_foreground_hold(tmp_path):
    r=runtime(tmp_path)
    i=Interaction()
    r.agent.proactive_state=SimpleNamespace(interaction=i,interacting=False)
    r.control.update("presence",{"active_hold_seconds":10,"semi_active_hold_seconds":20})
    i.interact(NOW)
    assert i.refresh(NOW+timedelta(seconds=9))==InteractionState.ACTIVE
    assert i.refresh(NOW+timedelta(seconds=10))==InteractionState.SEMI_ACTIVE
    assert i.refresh(NOW+timedelta(seconds=30))==InteractionState.IDLE
    i.interact(NOW+timedelta(seconds=40))
    assert i.refresh(NOW+timedelta(seconds=41))==InteractionState.ACTIVE
    i.foreground_finished(NOW+timedelta(seconds=60))
    assert i.refresh(NOW+timedelta(seconds=69))==InteractionState.ACTIVE
    assert i.refresh(NOW+timedelta(seconds=70))==InteractionState.SEMI_ACTIVE

def test_force_preserves_override_on_input_and_reset_renews_clock():
    i=Interaction(active_minutes=1,semi_active_minutes=1)
    i.interact(NOW)
    i.force_debug_state(InteractionState.SLEEP,NOW)
    i.interact(NOW+timedelta(seconds=10))
    assert i.refresh(NOW+timedelta(hours=1))==InteractionState.SLEEP
    i.force_debug_state(None,NOW+timedelta(hours=1))
    assert i.refresh(NOW+timedelta(hours=1,seconds=1))==InteractionState.ACTIVE

def test_settings_persist_and_update_existing_window(tmp_path):
    r=runtime(tmp_path)
    i=Interaction()
    r.agent.proactive_state=SimpleNamespace(interaction=i,interacting=False)
    i.interact(NOW)
    r.control.update("presence",{"active_hold_seconds":10,"semi_active_hold_seconds":20,"heartbeat_interval_seconds":5})
    assert i.active_until==NOW+timedelta(seconds=10)
    assert i.semi_active_until==NOW+timedelta(seconds=30)
    assert r.control.interval()==5
    restored=runtime(tmp_path)
    assert restored.control.presence()["active_hold_seconds"]==10
    assert restored.control.presence()["heartbeat_interval_seconds"]==5
    r.control.debug_override={"active_hold_seconds":5}
    assert runtime(tmp_path).control.debug_override is None

@pytest.mark.parametrize("key,value",[("heartbeat_interval_seconds",0),("active_hold_seconds",float("nan")),("semi_active_hold_seconds",-1),("heartbeat_multipliers",{"ACTIVE":float("inf")})])
def test_invalid_settings_do_not_change_memory_or_disk(tmp_path,key,value):
    r=runtime(tmp_path)
    before=r.control.presence()
    with pytest.raises(ValueError):r.control.update("presence",{key:value})
    assert r.control.presence()==before
    assert not r.control.path.exists()

def test_disabled_heartbeat_stops_automatic_activity(tmp_path):
    import asyncio
    r=runtime(tmp_path)
    r.control.update("presence",{"heartbeat_enabled":False})
    asyncio.run(r.run_tick())
    assert not r.last_tick

async def test_heartbeat_update_wakes_and_reschedules_waiter(tmp_path):
    import asyncio
    r=runtime(tmp_path)
    r.control.update("presence",{"heartbeat_interval_seconds":5})
    task=asyncio.create_task(r.control.wait_interval())
    await asyncio.sleep(0)
    first=r.control.next_tick_at
    r.control.update("presence",{"heartbeat_interval_seconds":15})
    for _ in range(8):await asyncio.sleep(0)
    assert r.control.next_tick_at > first+timedelta(seconds=9)
    r.control.update("presence",{"heartbeat_enabled":False})
    for _ in range(8):await asyncio.sleep(0)
    assert r.control.next_tick_at is None
    task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
