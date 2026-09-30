import json
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytest
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.core.message import Message, Role
from zhaoxi.current_cognition import CurrentCognitionMaintainer, CurrentCognitionService, CurrentCognitionStore
from zhaoxi.current_cognition.service import CurrentCognitionPatch
from zhaoxi.current_cognition.renderer import render_for_fast_chat
from zhaoxi.models.types import ModelResponse

TZ = ZoneInfo("Asia/Shanghai")

def service(tmp_path):
    return CurrentCognitionService(CurrentCognitionStore(tmp_path / "current.db"))

def update(key="job_search", title="秋招", summary="最近仍在推进秋招。", *, message="u1", overview="这几天秋招仍是主线。"):
    return CurrentCognitionPatch(decision="UPDATE", reason_code="ongoing_mainline",
        evidence_message_ids=[message], overview={"action": "replace", "value": overview},
        thread_ops=[{"action": "upsert", "key": key, "title": title, "summary": summary, "salience": 0.85}])

def apply(cognition, patch, *, message="u1", evidence="我最近仍在推进秋招"):
    return cognition.apply(patch, source_by_id={message: "user"}, evidence_by_id={message: evidence},
                           last_message_id=message)

def test_state_persists_and_injects_without_long_term_memory(tmp_path):
    cognition = service(tmp_path)
    apply(cognition, update())
    restored = service(tmp_path)
    system = ContextBuilder("人格", current_cognition_service=restored).build(Conversation())[0].content
    assert "秋招" in system and "[Current Cognition]" in system
    assert restored.state().threads[0].source_refs[0].message_id == "u1"
    explanation = restored.diagnostics()["thread_explanations"][0]
    assert explanation["why_exists"][0]["message_id"] == "u1"
    assert explanation["retention_reason"] == "recent_evidence"
    assert "narrative" not in restored.state().model_dump()

def test_keyed_upsert_alias_merge_and_resolve(tmp_path):
    cognition = service(tmp_path)
    apply(cognition, update())
    patch = CurrentCognitionPatch(decision="UPDATE", evidence_message_ids=["u2"],
        thread_ops=[{"action": "upsert", "key": "校招", "title": "秋招", "summary": "秋招最近仍在推进。", "salience": 0.7}])
    apply(cognition, patch, message="u2", evidence="秋招最近仍在推进")
    assert len(cognition.state().threads) == 1
    assert cognition.state().threads[0].key == "job_search"
    patch = CurrentCognitionPatch(decision="UPDATE", evidence_message_ids=["u3"],
        thread_ops=[{"action": "resolve", "key": "job_search"}])
    apply(cognition, patch, message="u3", evidence="秋招已经结束")
    assert cognition.state().threads == []
    assert "最近仍在推进秋招" not in cognition.snapshot()

def test_no_change_cursor_and_local_decay(tmp_path):
    cognition = service(tmp_path)
    old = datetime.now(TZ) - timedelta(days=4)
    apply(cognition, update(), evidence="秋招仍在推进")
    state = cognition.state()
    state.threads[0].last_evidence_at = old
    cognition.store.save(state)
    apply(cognition, CurrentCognitionPatch(reason_code="no_state_change"), message="u2", evidence="哈哈")
    assert cognition.state().threads[0].status == "cooling"
    assert cognition.state().last_processed_message_id == "u2"
    assert "降温中" in cognition.snapshot()
    state = cognition.state()
    state.threads[0].last_evidence_at = datetime.now(TZ) - timedelta(days=8)
    cognition.store.save(state)
    apply(cognition, CurrentCognitionPatch(), message="u3", evidence="哈哈")
    assert cognition.state().threads == []

def test_renderer_priority_budget_and_resolved_exclusion(tmp_path):
    cognition = service(tmp_path)
    apply(cognition, update())
    state = cognition.state()
    from zhaoxi.current_cognition.models import CognitionThread, JournalItem
    now = datetime.now(TZ)
    for i in range(8):
        state.threads.append(CognitionThread(key=f"k{i}", title="项目", summary="朝汐项目继续推进" * 5,
            salience=0.1, status="cooling", first_seen_at=now, last_updated_at=now, last_evidence_at=now))
    state.threads.append(CognitionThread(key="done", title="面试", summary="已经结束的面试",
        status="resolved", first_seen_at=now, last_updated_at=now, last_evidence_at=now))
    state.recent_changes.append(JournalItem(key="change", text="普通聊天已经走 FAST。",
        created_at=now, updated_at=now))
    rendered = render_for_fast_chat(state)
    assert len(rendered) <= 450
    assert "已经结束的面试" not in rendered
    assert rendered.index("还挂着") < rendered.index("刚变化")
    state.threads[0].last_evidence_at = now - timedelta(days=8)
    state.recent_changes[0].updated_at = now - timedelta(days=4)
    hidden = render_for_fast_chat(state)
    assert "最近仍在推进秋招" not in hidden
    assert "普通聊天已经走 FAST" not in hidden

def test_reject_untrusted_invention_and_queryable_detail(tmp_path):
    cognition = service(tmp_path)
    apply(cognition, update(), evidence="哈哈这个好蠢")
    assert cognition.state().overview == ""
    assert cognition.last_maintenance["rejection"] == "unsupported_claim"
    patch = CurrentCognitionPatch(decision="UPDATE", evidence_message_ids=["u2"],
        overview={"action": "replace", "value": "明天 10:00 有面试。"})
    apply(cognition, patch, message="u2", evidence="明天 10:00 有面试")
    assert cognition.state().overview == ""
    assert cognition.last_maintenance["rejection"] == "tool_or_queryable_detail"
    patch = CurrentCognitionPatch(decision="UPDATE", evidence_message_ids=["u3"],
        watch_ops=[{"action": "upsert", "key": "interview_tomorrow", "text": "明天要去面试"}])
    apply(cognition, patch, message="u3", evidence="明天要去面试")
    assert cognition.state().watch_items == []

def test_legacy_migrates_once_and_keeps_read_only_backup(tmp_path):
    path = tmp_path / "old.db"
    old = {"version": 9, "narrative": "用户最近持续参与秋招。还有很多已经过时的长篇分析。",
           "ongoing_threads": ["仍在参与秋招", "明天 10:00 面试"],
           "attention": ["旧便签"], "last_processed_message_id": "u0"}
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE current_cognition(id INTEGER PRIMARY KEY, state_json TEXT)")
        db.execute("INSERT INTO current_cognition VALUES (1,?)", (json.dumps(old, ensure_ascii=False),))
    cognition = CurrentCognitionService(CurrentCognitionStore(path))
    state = cognition.state()
    assert state.version == 2 and "用户" not in state.overview
    assert len(state.threads) == 1 and state.last_processed_message_id == "u0"
    with sqlite3.connect(path) as db:
        assert json.loads(db.execute("SELECT state_json FROM current_cognition_legacy_backup").fetchone()[0]) == old
    assert cognition.state().model_dump() == state.model_dump()

class FakeProvider:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.requests = []
    async def generate(self, messages, tools=None, **kwargs):
        self.requests.append((messages, kwargs))
        result = next(self.outputs)
        if isinstance(result, Exception):
            raise result
        return ModelResponse(content=json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else result)

@pytest.mark.asyncio
async def test_local_gate_skips_jokes_and_single_emotion(tmp_path):
    cognition = service(tmp_path)
    provider = FakeProvider([])
    maintainer = CurrentCognitionMaintainer(cognition, provider)
    for message_id, content in (("u1", "哈哈这个好蠢"), ("u2", "今天有点烦")):
        assert await maintainer.maintain([Message(message_id=message_id, role=Role.USER, content=content)]) == "NO_CHANGE"
    assert provider.requests == []
    assert cognition.state().last_processed_message_id is None
    assert cognition.last_maintenance["model_call"] is False

@pytest.mark.asyncio
async def test_backlog_keeps_earlier_state_signal(tmp_path):
    cognition = service(tmp_path)
    provider = FakeProvider([{"decision": "NO_CHANGE"}])
    messages = [Message(message_id="u1", role=Role.USER, content="最近秋招一直没有进展")]
    messages += [Message(message_id=f"u{i}", role=Role.USER, content="哈哈") for i in range(2, 12)]
    assert await CurrentCognitionMaintainer(cognition, provider).maintain(messages) == "NO_CHANGE"
    payload = json.loads(provider.requests[0][0][1].content)
    assert any(item["id"] == "u1" for item in payload["new_messages"])
    assert len(payload["new_messages"]) <= 8

@pytest.mark.asyncio
async def test_maintainer_structured_ops_and_failure_diagnostics(tmp_path):
    cognition = service(tmp_path)
    provider = FakeProvider([
        {"decision": "UPDATE", "evidence_message_ids": ["u1"],
         "overview": {"action": "replace", "value": "这几天秋招仍在推进。"},
         "thread_ops": [{"action": "upsert", "key": "job_search", "title": "秋招",
                         "summary": "秋招仍在推进。", "salience": 0.8}]},
        RuntimeError("offline")
    ])
    maintainer = CurrentCognitionMaintainer(cognition, provider)
    assert await maintainer.maintain([Message(message_id="u1", role=Role.USER, content="最近秋招仍在推进")]) == "UPDATE"
    assert cognition.last_maintenance["ops_count"] == 2
    assert await maintainer.maintain([Message(message_id="u2", role=Role.USER, content="最近秋招仍在推进")]) == "FAILED"
    assert cognition.last_maintenance["error_type"] == "RuntimeError"

def test_no_change_rejects_hidden_operations():
    with pytest.raises(ValueError):
        CurrentCognitionPatch(decision="NO_CHANGE", thread_ops=[{"action": "remove", "key": "job_search"}])
