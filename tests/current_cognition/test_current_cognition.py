import json
import sqlite3

import pytest

from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.core.message import Message, Role
from zhaoxi.current_cognition import CurrentCognitionMaintainer, CurrentCognitionService, CurrentCognitionStore
from zhaoxi.current_cognition.service import CurrentCognitionPatch
from zhaoxi.models.types import ModelResponse


def service(tmp_path, legacy=None):
    return CurrentCognitionService(CurrentCognitionStore(tmp_path / "current.db", legacy_stm_path=legacy))


def update(to, *, old="", reason="ongoing_mainline", source="u1", **extra):
    return CurrentCognitionPatch(decision="UPDATE", reason_code=reason,
        evidence_message_ids=[source], narrative_patch=[{"from": old, "to": to}], **extra)


def apply(stm, patch, source="u1", content="我最近持续参与秋招，并且继续开发朝汐"):
    return stm.apply(patch, source_by_id={source: "user"}, evidence_by_id={source: content}, last_message_id=source)


def test_persistence_beyond_forty_raw_messages(tmp_path):
    cognition = service(tmp_path)
    apply(cognition, update("近期仍在参与秋招，同时持续开发朝汐。"))
    conversation = Conversation(max_messages=40)
    for index in range(50):
        conversation.add_user(f"普通闲聊 {index}")
    restored = service(tmp_path)
    system = ContextBuilder("人格", current_cognition_service=restored).build(conversation)[0].content
    assert "[Current Cognition]" in system and "秋招" in system
    assert len(conversation.messages) <= 40


def test_no_change_does_not_rephrase_and_keeps_processing_cursor(tmp_path):
    cognition = service(tmp_path)
    apply(cognition, update("近期仍在参与秋招。"))
    before = cognition.state()
    apply(cognition, CurrentCognitionPatch(decision="NO_CHANGE", reason="一顿饭不改变整体理解"),
          source="u2", content="中午吃了面")
    after = cognition.state()
    assert after.narrative == before.narrative
    assert after.version == before.version
    assert after.last_processed_message_id == "u2"


def test_empty_bootstrap_no_change_preserves_cursor(tmp_path):
    cognition = service(tmp_path)
    cognition.apply(CurrentCognitionPatch(decision="NO_CHANGE"),
                    source_by_id={"u1": "user"}, last_message_id="u1")
    assert cognition.state().last_processed_message_id is None


def test_targeted_change_and_user_correction(tmp_path):
    cognition = service(tmp_path)
    apply(cognition, update("近期在参与秋招，准备算法岗，同时持续开发朝汐。"))
    apply(cognition, update("不再走算法岗，转向后端和 AI 应用。", old="准备算法岗", reason="state_change", source="u2"),
          source="u2", content="不对，我已经不走算法岗了，还是后端 + AI 应用")
    assert "算法岗" in cognition.state().narrative
    assert "准备算法岗" not in cognition.state().narrative
    assert "朝汐" in cognition.state().narrative
    assert cognition.diagnostics()["last_maintenance"]["before_after_diff"]


def test_one_off_and_tool_details_and_psychology_rejected(tmp_path):
    cognition = service(tmp_path)
    for index, text in enumerate(("今天吃了午餐", "数据库 Navicat 表更新了", "通过动漫逃避秋招压力")):
        reason = "state_change" if index else "cross_context"
        apply(cognition, update(text, reason=reason, source=f"u{index}"),
              source=f"u{index}", content="秋招忙，最近看动漫")
        assert cognition.state().narrative == ""
        assert cognition.diagnostics()["last_maintenance"]["rejection"]


def test_unrelated_model_invention_is_not_saved(tmp_path):
    cognition = service(tmp_path)
    apply(cognition, update("近期正在准备出国留学。"), content="哈哈这张图好蠢")
    assert cognition.state().narrative == ""
    assert cognition.diagnostics()["last_maintenance"]["rejection"] == "unsupported_claim"


def test_repeated_topic_requires_three_distinct_user_messages(tmp_path):
    cognition = service(tmp_path)
    for index in range(2):
        patch = CurrentCognitionPatch(decision="NO_CHANGE", observations=[
            {"key": "动漫", "source_message_id": f"u{index}"}])
        apply(cognition, patch, source=f"u{index}", content="今天聊动漫")
    apply(cognition, update("近期动漫相关话题明显增多。", reason="repeated_recent_theme", source="u2",
                            observations=[{"key": "动漫", "source_message_id": "u2"}]),
          source="u2", content="又聊动漫")
    assert cognition.state().observations[0].count == 3
    assert "动漫" in cognition.state().narrative


def test_legacy_database_is_reference_only_and_not_mutated(tmp_path):
    legacy = tmp_path / "stm.db"
    with sqlite3.connect(legacy) as db:
        db.execute("CREATE TABLE short_term_memory (id INTEGER PRIMARY KEY, state_json TEXT)")
        db.execute("INSERT INTO short_term_memory VALUES (1, ?)", (json.dumps({"overview": "旧待办：买奶茶"}),))
    cognition = service(tmp_path, legacy)
    assert "买奶茶" in cognition.store.legacy_reference()
    assert cognition.state().narrative == ""
    assert cognition.snapshot().endswith("近期状态尚未形成。")
    with sqlite3.connect(legacy) as db:
        assert "买奶茶" in json.loads(db.execute("SELECT state_json FROM short_term_memory").fetchone()[0])["overview"]


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
async def test_maintainer_no_change_update_failure_and_bootstrap_reference(tmp_path):
    legacy = tmp_path / "stm.db"
    with sqlite3.connect(legacy) as db:
        db.execute("CREATE TABLE short_term_memory (id INTEGER PRIMARY KEY, state_json TEXT)")
        db.execute("INSERT INTO short_term_memory VALUES (1, ?)", (json.dumps({"overview": "旧待办：买奶茶"}),))
    cognition = service(tmp_path, legacy)
    provider = FakeProvider([
        {"decision": "NO_CHANGE", "reason": "一次闲聊"},
        {"decision": "UPDATE", "reason_code": "ongoing_mainline", "evidence_message_ids": ["u2"],
         "narrative_patch": [{"from": "", "to": "近期持续参与秋招。"}]},
        RuntimeError("offline"),
    ])
    maintainer = CurrentCognitionMaintainer(cognition, provider)
    messages = [Message(message_id="u1", role=Role.USER, content="哈哈")]
    assert await maintainer.maintain(messages) == "NO_CHANGE"
    assert "legacy_reference_untrusted" in json.loads(provider.requests[0][0][1].content)
    messages.append(Message(message_id="u2", role=Role.USER, content="最近仍在参与秋招"))
    assert await maintainer.maintain(messages) == "UPDATE"
    messages.append(Message(message_id="u3", role=Role.USER, content="继续"))
    assert await maintainer.maintain(messages) == "FAILED"
    assert "秋招" in service(tmp_path).snapshot()
    assert cognition.diagnostics()["last_maintenance"]["decision"] == "FAILED"
    assert len(provider.requests) == 3


@pytest.mark.asyncio
async def test_tool_only_process_does_not_call_maintainer_model(tmp_path):
    cognition = service(tmp_path)
    provider = FakeProvider([])
    result = await CurrentCognitionMaintainer(cognition, provider).maintain([
        Message(message_id="t1", role=Role.TOOL,
                content='{"success":true,"content":"Navicat 数据库表已更新"}')])
    assert result == "NO_CHANGE"
    assert cognition.state().narrative == ""
    assert cognition.state().last_processed_message_id == "t1"
    assert provider.requests == []


@pytest.mark.asyncio
async def test_validation_failure_keeps_bootstrap_window_and_field_detail(tmp_path):
    cognition = service(tmp_path)
    invalid = {"decision": "UPDATE", "narrative_patch": [{"from": "", "to": 123}]}
    provider = FakeProvider([invalid, invalid])
    result = await CurrentCognitionMaintainer(cognition, provider).maintain([
        Message(message_id="u1", role=Role.USER, content="持续开发朝汐"),
    ], background=True)
    assert result == "FAILED"
    state = cognition.state()
    assert state.last_processed_message_id is None
    assert state.last_maintenance["field_path"] == "narrative_patch.0.to"
    assert state.last_maintenance["attempt"] == 2
    assert state.last_maintenance["response_chars"] > 0


def test_precise_agenda_and_lifehud_fields_do_not_enter_narrative(tmp_path):
    cognition = service(tmp_path)
    for index, text in enumerate(("明天 13:00 有笔试", "昨晚睡眠 6.5小时，消耗 500kcal")):
        apply(cognition, update(text, reason="state_change", source=f"u{index}"),
              source=f"u{index}", content=text)
        assert cognition.state().narrative == ""
        assert cognition.diagnostics()["last_maintenance"]["rejection"] == "tool_or_queryable_detail"


def test_no_change_rejects_hidden_edits():
    with pytest.raises(ValueError):
        CurrentCognitionPatch(decision="NO_CHANGE", threads_add=["偷偷新增"])
