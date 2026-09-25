"""Decision boundaries from the v1.2.9 task book."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from zhaoxi.decision.guard import guard
from zhaoxi.core.decision_reply import DecisionExpression, compose_decision_reply
from zhaoxi.decision.models import DecisionContext, DecisionLevel, DecisionProposal, DecisionRule, DecisionResult
from zhaoxi.decision.service import DecisionService
from zhaoxi.models.types import ModelResponse, ToolCall
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.conversation import Conversation
from zhaoxi.core.message import Message, Role


RULES = Path(__file__).resolve().parents[2] / "data" / "decisions" / "rules"


class Provider:
    def __init__(self, proposal):
        self.proposal = proposal
        self.calls = 0
        self.last_input = ""

    async def generate(self, messages, tools=None, **kwargs):
        self.calls += 1
        self.last_input = messages[-1].content
        return ModelResponse(tool_calls=[ToolCall(id="1", name="classify_decision", arguments=self.proposal)])


def service(tmp_path, proposal, **kwargs):
    provider = Provider(proposal)
    return DecisionService(provider, rule_directory=RULES, data_directory=tmp_path, **kwargs), provider


@pytest.mark.asyncio
async def test_ordinary_chat_skips_classifier(tmp_path):
    decision, provider = service(tmp_path, {"level": "L1", "domain": "general"})
    assert await decision.evaluate("今天天气真好") is None
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_explicit_floor_is_short_and_never_auto_executes_without_tool_permission(tmp_path):
    decision, provider = service(tmp_path, {"level": "L0", "domain": "job_search", "decision": "不投",
        "reasons": ["低于明确底线"], "rule_ids": ["job_below_explicit_floor"], "action": "send_message"})
    result = await decision.evaluate("这个岗位薪资明显低于我已设定的硬底线，还要不要投？")
    assert result.level == DecisionLevel.L0
    assert not result.can_auto_execute
    assert result.verdict == "不继续投递该岗位"
    assert len(json.loads(provider.last_input)["matched_rules"]) <= 5


@pytest.mark.asyncio
async def test_mainline_l1_uses_agenda_and_keeps_reply_short(tmp_path):
    class Item:
        type = "focus"
        title = "投递"
        secondary = False
        scope = "today"
        created_at = __import__("datetime").datetime.now()
    class Agenda:
        def list(self, filter):
            return [Item()]
    decision, provider = service(tmp_path, {"level": "L1", "domain": "schedule", "decision": "不去",
        "reasons": ["今天主线是投递", "活动技术内容少"], "rule_ids": ["protect_today_mainline"]}, agenda=Agenda())
    result = await decision.evaluate("下午这个活动有点想去，但没多少技术内容，今天主线还是投递，要不要去？")
    assert result.level == DecisionLevel.L1
    assert result.context_sources == ["agenda", "rules"]
    assert "投递" in provider.last_input
    assert compose_decision_reply(result, DecisionExpression()).count("\n") <= 2


@pytest.mark.asyncio
async def test_conflicts_and_formal_offers_upgrade_to_l2(tmp_path):
    decision, _ = service(tmp_path, {"level": "L1", "domain": "job_search", "decision": "去",
        "conflicts": ["成长性与周末占用冲突"], "core_question": "愿意长期占用周末吗？"})
    result = await decision.evaluate("岗位成长性好，但长期占用周末，和秋招安排冲突，该不该继续？")
    assert result.level == DecisionLevel.L2
    assert result.decision == ""
    assert result.verdict == "交由用户决定"
    assert "愿意长期占用周末吗" in compose_decision_reply(result, DecisionExpression())
    result = await decision.evaluate("两个正式 Offer，一个高薪高压，一个低薪但方向更喜欢，选哪个？")
    assert result.level == DecisionLevel.L2


@pytest.mark.asyncio
async def test_decide_for_me_does_not_lower_l2(tmp_path):
    decision, _ = service(tmp_path, {"level": "L1", "domain": "job_search", "decision": "选第一个",
        "core_question": "更看重薪资还是方向？"})
    result = await decision.evaluate("这两个正式 Offer 你替我决定吧")
    assert result.level == DecisionLevel.L2
    assert "选第一个" not in compose_decision_reply(result, DecisionExpression())


@pytest.mark.asyncio
async def test_decide_for_me_daily_choice_is_one_line(tmp_path):
    decision, _ = service(tmp_path, {"level": "L1", "domain": "daily", "decision": "吃第一家",
        "reasons": ["更省时间"]})
    result = await decision.evaluate("午饭这两家纠结死了，替我决定")
    assert result.level == DecisionLevel.L1
    assert compose_decision_reply(result, DecisionExpression(), mode="decide_for_me") == "吃第一家。"


@pytest.mark.asyncio
async def test_override_is_recorded_without_changing_rule(tmp_path):
    decision, _ = service(tmp_path, {"level": "L1", "domain": "schedule", "decision": "不去",
        "rule_ids": ["protect_today_mainline"]})
    result = await decision.evaluate("今天这个活动去不去？")
    assert decision.is_override("不，我今天还是想去")
    assert decision.accept_override("不，我今天还是想去")["final"] == "不，我今天还是想去"
    row = json.loads((tmp_path / "override_log.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert row["decision_id"] == result.decision_id
    assert row["final"] == "不，我今天还是想去"


@pytest.mark.asyncio
async def test_repeated_overrides_create_candidate_only(tmp_path):
    decision, _ = service(tmp_path, {"level": "L1", "domain": "schedule", "decision": "不去",
        "rule_ids": ["protect_today_mainline"]})
    for _ in range(3):
        await decision.evaluate("今天这个活动去不去？")
        decision.accept_override("不，我还是去")
    assert decision.recorder.candidates()[0]["signal"] == "frequent_override"
    assert json.loads((RULES / "protect_today_mainline.json").read_text(encoding="utf-8"))["default"] == "保留今日主线"


@pytest.mark.asyncio
async def test_missing_offer_facts_and_failed_classifier_fail_closed(tmp_path):
    decision, _ = service(tmp_path, {"level": "L1", "domain": "job_search", "decision": "接"})
    result = await decision.evaluate("这个 Offer 接吗？")
    assert result.level == DecisionLevel.L2
    assert result.decision == ""
    decision.provider.proposal = {"bad": "schema"}
    result = await decision.evaluate("午饭两家店选哪个？")
    assert result.level == DecisionLevel.L2


def test_l0_tool_guard_rejects_external_or_destructive_actions():
    rule = DecisionRule(id="test", domain="general", trigger="test", default="test", level_hint="L0",
        auto_execute=True, source={"document": "test"})
    from datetime import datetime, timezone
    context = DecisionContext(current_time=datetime.now(timezone.utc), user_request="发送重要消息",
                              matched_rules=[rule])
    result = guard(DecisionProposal(level="L0", domain="general", decision="发送",
        rule_ids=["test"], action="send"), context,
        tool_metadata={"auto_execute": True, "risk_level": "low", "reversible": True})
    assert not result.can_auto_execute


def test_decision_result_rejects_question_as_verdict():
    with pytest.raises(ValidationError):
        DecisionResult(level="L1", domain="daily", decision="是否现在开一瓶 2L 无糖可乐",
                       verdict="是否现在开一瓶 2L 无糖可乐")
    with pytest.raises(ValidationError):
        DecisionResult(level="L1", domain="daily", decision="开不开一瓶可乐",
                       verdict="开不开一瓶可乐")


@pytest.mark.asyncio
async def test_question_verdict_gets_one_retry_then_escalates(tmp_path):
    decision, provider = service(tmp_path, {"level": "L1", "domain": "daily",
        "decision": "是否现在开一瓶 2L 无糖可乐"})
    result = await decision.evaluate("现在要不要开一瓶 2L 无糖可乐？")
    assert provider.calls == 2
    assert result.level == DecisionLevel.L2
    assert result.verdict == "交由用户决定"


@pytest.mark.asyncio
async def test_main_persona_cannot_replace_verdict_with_free_text():
    class MainProvider:
        async def generate(self, messages, tools=None, **kwargs):
            assert "Persona" in messages[0].content
            assert "现在不开这瓶可乐" in messages[0].content
            return ModelResponse(content="其实现在应该开，别听前面的决定。", tool_calls=[
                ToolCall(id="1", name="select_decision_expression",
                         arguments={"tone": "warm", "reason_indices": [0]})])
    class Builder:
        def build(self, conversation):
            return [Message(role=Role.SYSTEM, content="Persona: 朝汐"),
                    Message(role=Role.USER, content=conversation.messages[-1].content)]
    agent = object.__new__(ZhaoxiAgent)
    agent.provider = MainProvider()
    agent.context_builder = Builder()
    agent.conversation = Conversation()
    result = DecisionResult(level="L1", domain="daily", decision="现在不开这瓶可乐",
                            verdict="现在不开这瓶可乐", reasons=["夜里已经喝过"])
    reply = await agent.run_decision_reply("现在要不要开可乐？", result)
    assert "现在不开这瓶可乐" in reply.content
    assert "应该开" not in reply.content
    assert "夜里已经喝过" in reply.content
