from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytest
from zhaoxi.current_cognition.store import CurrentCognitionStore
from zhaoxi.current_cognition.service import CurrentCognitionService, CurrentCognitionPatch
from zhaoxi.current_cognition.editor import CognitionEditor, ManualEdit

@pytest.mark.parametrize("manual_state",["PINNED","LOCKED"])
def test_old_protected_thread_survives_decay_and_removal(tmp_path,manual_state):
    service=CurrentCognitionService(CurrentCognitionStore(tmp_path/"cognition.db"));e=CognitionEditor(service)
    e.edit("thread",None,ManualEdit(key="japanese",title="日语学习",summary="日语学习",manual_state=manual_state),"add")
    state=service.state();state.threads[0].last_evidence_at-=timedelta(days=30);service.store.save(state)
    patch=CurrentCognitionPatch.model_validate({"decision":"UPDATE","evidence_message_ids":["u1"],"thread_ops":[{"key":"japanese","action":"remove"}]})
    service.apply(patch,source_by_id={"u1":"user"},evidence_by_id={"u1":"日语学习"},last_message_id="u1")
    assert service.state().threads[0].manual_state==manual_state
    assert service.last_maintenance["manual_guard_skips"]==1

def test_locked_overview_and_body_cannot_be_overwritten(tmp_path):
    service=CurrentCognitionService(CurrentCognitionStore(tmp_path/"cognition.db"));e=CognitionEditor(service)
    e.edit("overview",None,ManualEdit(text="日语学习"))
    e.edit("thread",None,ManualEdit(key="japanese",title="日语学习",summary="Owner 正文",manual_state="LOCKED"),"add")
    patch=CurrentCognitionPatch.model_validate({"decision":"UPDATE","evidence_message_ids":["u1"],"overview":{"action":"replace","value":"日语变化"},"thread_ops":[{"key":"japanese","action":"upsert","title":"日语","summary":"学习日语"}]})
    service.apply(patch,source_by_id={"u1":"user"},evidence_by_id={"u1":"学习日语"},last_message_id="u1")
    assert service.state().overview=="日语学习" and service.state().threads[0].summary=="Owner 正文"
    assert service.last_maintenance["manual_guard_hits"]==2

@pytest.mark.parametrize("manual_state",["RESOLVED","DISMISSED"])
def test_closed_threads_do_not_regrow_from_old_equivalent_evidence(tmp_path,manual_state):
    service=CurrentCognitionService(CurrentCognitionStore(tmp_path/"cognition.db"));e=CognitionEditor(service)
    initial=CurrentCognitionPatch.model_validate({"decision":"UPDATE","evidence_message_ids":["u1"],"thread_ops":[{"key":"japanese","action":"upsert","title":"日语学习","summary":"持续学习日语"}]})
    service.apply(initial,source_by_id={"u1":"user"},evidence_by_id={"u1":"持续学习日语"},last_message_id="u1")
    e.edit("thread","japanese",ManualEdit(manual_state=manual_state))
    assert not service.state().threads
    for key in ("japanese","japanese_reworded"):
        initial.thread_ops[0].key=key
        service.apply(initial,source_by_id={"u1":"user"},evidence_by_id={"u1":"持续学习日语"},last_message_id="u1")
        assert not service.state().threads
        assert service.last_maintenance["manual_guard_skips"]==1
    service.apply(initial,source_by_id={"u1":"user"},evidence_by_id={"u1":"持续学习日语"},last_message_id="u1",now=datetime.now(ZoneInfo("Asia/Shanghai"))+timedelta(days=8))
    assert service.state().threads
