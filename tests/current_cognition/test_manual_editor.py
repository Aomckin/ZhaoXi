import pytest
from zhaoxi.current_cognition.store import CurrentCognitionStore
from zhaoxi.current_cognition.service import CurrentCognitionService
from zhaoxi.current_cognition.editor import CognitionEditor, ManualEdit

@pytest.fixture
def editor(tmp_path):return CognitionEditor(CurrentCognitionService(CurrentCognitionStore(tmp_path/"cognition.db")))

def test_overview_and_thread_revisions_persist_and_undo(editor):
    result=editor.edit("overview",None,ManualEdit(text="最近在开发朝汐"))
    assert result["state"]["overview_manual"]["source"]=="OWNER_MANUAL"
    added=editor.edit("thread",None,ManualEdit(key="zhaoxi",title="朝汐",summary="继续开发"),"add")
    item=editor.service.state().threads[0]
    assert item.source=="OWNER_MANUAL" and item.manual_revision==1
    assert editor.service.store.revisions()["total"]==2
    editor.undo(added["revision_id"])
    assert not editor.service.state().threads
    assert editor.service.state().overview=="最近在开发朝汐"
    with pytest.raises(ValueError):editor.undo()

@pytest.mark.parametrize("target",["watch","change"])
def test_items_edit_complete_delete_and_undo(editor,target):
    editor.edit(target,None,ManualEdit(key="item",text="持续学习日语"),"add")
    editor.edit(target,"item",ManualEdit(text="继续学习日语",manual_state="LOCKED"))
    attr="watch_items" if target=="watch" else "recent_changes"
    assert getattr(editor.service.state(),attr)[0].manual_state=="LOCKED"
    result=editor.edit(target,"item",ManualEdit(),"delete")
    assert not getattr(editor.service.state(),attr)
    editor.undo(result["revision_id"])
    assert getattr(editor.service.state(),attr)[0].text=="继续学习日语"

def test_merge_and_targeted_undo_preserve_other_work(editor):
    editor.edit("thread",None,ManualEdit(key="a",title="日语学习",summary="学习日语"),"add")
    editor.edit("thread",None,ManualEdit(key="b",title="日语练唱",summary="学习日语歌"),"add")
    merged=editor.edit("thread","a",ManualEdit(summary="学习日语与练唱",merge_keys=["b"]))
    assert len(editor.service.state().threads)==1
    state=editor.service.state();state.overview="后台更新的概览";editor.service.store.save(state)
    editor.undo(merged["revision_id"])
    assert len(editor.service.state().threads)==2
    assert editor.service.state().overview=="后台更新的概览"

def test_optimistic_version_and_undo_conflict_are_fail_closed(editor):
    added=editor.edit("thread",None,ManualEdit(key="a",title="日语",summary="日语学习"),"add")
    with pytest.raises(ValueError):editor.edit("thread","a",ManualEdit(summary="更新",expected_version=0))
    state=editor.service.state();state.threads[0].summary="后台补充";editor.service.store.save(state)
    with pytest.raises(ValueError):editor.undo(added["revision_id"])
    assert editor.service.state().threads[0].summary=="后台补充"
