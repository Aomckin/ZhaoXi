"""V148-02: abstract first, admit second, never silently fall back to a quote."""
import json

import pytest
from test_decision_awareness import make_agent, reply
from zhaoxi.decision.history import ChoiceHistory
from zhaoxi.decision.models import DecisionAwarenessTrace
from zhaoxi.decision.reply import REPLY_FORMAT
from zhaoxi.models.types import ModelResponse

SOURCE = "狗子，你去帮我采购无糖可乐吧。"
QUESTION = "本次补购无糖可乐，应选什么包装规格和购买数量？"


@pytest.mark.parametrize("question", [SOURCE, "狗子 你去帮我采购无糖可乐吧?", "你去帮我采购无糖可乐"])
@pytest.mark.parametrize("fast", [False, True])
async def test_copied_message_never_becomes_decision_and_reply_needs_no_extra_call(tmp_path, question, fast):
    agent, provider = make_agent(tmp_path, [reply("唔，先看下能买到哪些。", "ADVISE", decision_question=question)], fast=fast)
    result = await agent.run_natural(SOURCE)
    assert result.content == "唔，先看下能买到哪些。"
    assert len(provider.calls) == 1
    assert agent.decision_awareness.history.list() == []
    assert agent.decision_awareness.recent_traces[-1]["registration_status"] == "copied_user_text"
    assert agent.decision_awareness.pending_choice(agent.conversation) is None


@pytest.mark.parametrize("kind", ["EXECUTION", "CORRECTION", "CONTINUATION", "NONE"])
async def test_non_new_choice_does_not_register_even_when_model_offers_advice(tmp_path, kind):
    agent, provider = make_agent(tmp_path, [reply("嗯，收到。", "ADVISE", decision_kind=kind, decision_question=QUESTION)])
    await agent.run(SOURCE)
    assert not agent.decision_awareness.history.list()
    assert len(provider.calls) == 1


@pytest.mark.parametrize("fast", [False, True])
async def test_context_abstracted_problem_is_saved_separately_from_advice(tmp_path, fast):
    payload = {"reply": "这次买 2L 两瓶就够。", "awareness": {
        "mode": "PICK", "decision_kind": "NEW", "decision_question": QUESTION,
        "agent_recommendation": "2L 两瓶"}, "escalation": None}
    agent, provider = make_agent(tmp_path, [ModelResponse(content=json.dumps(payload, ensure_ascii=False))], fast=fast)
    agent.conversation.add_user("家里无糖可乐喝完了，打算补点，规格和数量都还没定。")
    agent.conversation.add_assistant("我看看本次补货该怎么买。")
    result = await agent.run_natural("那这次选哪种买多少？")
    rows = agent.decision_awareness.history.list()
    assert result.content == payload["reply"] and len(provider.calls) == 1
    assert len(rows) == 1
    row = rows[0]
    assert row["summary"] == row["decision_question"] == QUESTION
    assert row["summary"] != agent.conversation.messages[-2].content
    assert row["suggestion"] == "2L 两瓶" and row["question_status"] == "abstracted"
    assert row["source_message_id"] == agent.conversation.messages[-2].message_id
    assert "省略称呼" in provider.calls[0][0].content


@pytest.mark.parametrize(("question", "recommendation", "status"), [
    (None, "买两瓶", "missing_decision_question"),
    ("买两瓶就足够了。", "买两瓶就足够了", "recommendation_as_question"),
])
async def test_unusable_metadata_preserves_natural_reply_and_does_not_create_placeholder(tmp_path, question, recommendation, status):
    agent, provider = make_agent(tmp_path, [reply("两瓶就够啦。", "PICK", decision_question=question, agent_recommendation=recommendation)])
    await agent.run_direct("这个规格该买多少瓶？")
    assert not agent.decision_awareness.history.list()
    assert agent.decision_awareness.recent_traces[-1]["registration_status"] == status
    assert len(provider.calls) == 1


def test_storage_rejects_missing_question_instead_of_using_summary_fallback(tmp_path):
    history = ChoiceHistory(tmp_path)
    with pytest.raises(ValueError, match="missing_decision_question"):
        history.record("one", DecisionAwarenessTrace(mode="ADVISE", decision_kind="NEW"), SOURCE, scope="owner:web:local:")
    assert not (tmp_path / "choice_history.jsonl").exists()


def test_storage_itself_rejects_copied_problem(tmp_path):
    history = ChoiceHistory(tmp_path)
    with pytest.raises(ValueError, match="copied_user_text"):
        history.record("one", DecisionAwarenessTrace(mode="ADVISE", decision_kind="NEW", decision_question=SOURCE),
                       scope="owner:web:local:", source_text=SOURCE)
    assert history.list() == []


def test_old_episode_is_labelled_without_rewriting_original_bytes(tmp_path):
    path = tmp_path / "choice_history.jsonl"
    original = json.dumps({"event": "decision", "decision_id": "old", "schema_version": 3,
        "timestamp": "2026-10-10T11:54:32+00:00", "scope": "owner:web:local:", "summary": SOURCE,
        "mode": "ADVISE", "suggestion": "点外卖无糖可乐，2L 两瓶"}, ensure_ascii=False) + "\n"
    path.write_text(original, encoding="utf-8")
    history = ChoiceHistory(tmp_path)
    assert history.list()[0]["summary"] == SOURCE
    assert history.get("old")["question_status"] == "legacy_unabstracted"
    assert "decision_question" not in history.get("old")
    assert path.read_text(encoding="utf-8") == original


def test_primary_schema_requests_explicit_problem_and_kind():
    schema = REPLY_FORMAT["json_schema"]["schema"]["$defs"]["DecisionAwarenessTrace"]
    assert {"mode", "decision_kind", "decision_question"} <= set(schema["required"])
    assert "不得摘抄用户原话" in schema["properties"]["decision_question"]["description"]
