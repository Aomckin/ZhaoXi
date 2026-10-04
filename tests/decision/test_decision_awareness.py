"""Decision 2.0 contracts: one reply, real context receipts and episodic choices."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from conftest import FakeProvider

from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.cognitive.coordinator import CognitiveCoordinator
from zhaoxi.cognitive.fast_gate import FastDialogueGate
from zhaoxi.cognitive.router import CognitiveRouter
from zhaoxi.decision.awareness import split_awareness
from zhaoxi.decision.context import ReadDecisionContext, relevant_cognition
from zhaoxi.decision.history import ChoiceHistory
from zhaoxi.decision.rules import RuleStore
from zhaoxi.models.types import ModelResponse, ToolCall
from zhaoxi.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[2]


def reply(content, mode=None, **values):
    marker = ("<decision-awareness>" + json.dumps({"mode": mode, **values}, ensure_ascii=False)
              + "</decision-awareness>") if mode else ""
    return ModelResponse(content=content + marker)


def call(name, **arguments):
    return ModelResponse(tool_calls=[ToolCall(id=name, name=name, arguments=arguments)])


def make_agent(tmp_path, responses, *, fast=False, legacy=False):
    provider = FakeProvider(responses)
    agent = ZhaoxiAgent(provider=provider, registry=ToolRegistry(), context_builder=ContextBuilder("朝汐"),
                        decision_mode="legacy" if legacy else "agency")
    agent.decision_awareness.history = ChoiceHistory(tmp_path / "choices")
    agent.decision_awareness.principles = RuleStore(ROOT / "data/decisions/rules")
    if fast:
        agent.cognitive = CognitiveCoordinator(agent=agent, router=CognitiveRouter(provider),
            fast_gate=FastDialogueGate(decision_mode=agent.decision_mode))
        agent.cognitive.router.route = AsyncMock(side_effect=AssertionError("no router for short choices"))
    return agent, provider


@pytest.mark.parametrize(("question", "answer"), [
    ("这几个吃啥？", "辣椒炒肉，就它。"),
    ("无糖可乐买几瓶？", "两瓶。"),
    ("这个零食买不买？", "买一包。"),
    ("我在货架前站半天了。", "右边那个，就它。"),
    ("这两个差不多的饭选哪个？", "第一个。"),
])
async def test_fast_pick_has_no_classifier_rule_or_extra_model(tmp_path, question, answer):
    agent, provider = make_agent(tmp_path, [reply(answer, "PICK", agent_recommendation=answer)], fast=True)
    agent.decision_service = SimpleNamespace(evaluate=AsyncMock(side_effect=AssertionError("legacy")))
    memory = SimpleNamespace(retrieve=AsyncMock(side_effect=AssertionError("no recall for PICK")))
    agent.context_builder.memory_retriever = memory
    agent.decision_awareness.memory = memory
    result = await agent.run_natural(question)
    assert result.content == answer
    assert len(provider.calls) == 1 and provider.tool_schemas[0] is None
    assert provider.options[0]["response_format"]["type"] == "json_schema"
    agent.cognitive.router.route.assert_not_awaited()
    assert agent.decision_awareness.diagnostics()["latest"]["mode"] == "PICK"
    assert agent.last_reply_protocol["awareness"] == "valid" and agent.last_reply_protocol["mode"] == "PICK"
    row = agent.decision_awareness.history.list()[0]
    assert row["suggestion"] == answer and row["schema_version"] == 3
    assert row["context_refs"] == [] and row["user_final_choice"] is None
    assert "<decision-awareness>" not in json.dumps(
        [m.model_dump(mode="json") for m in agent.conversation.messages], ensure_ascii=False)


async def test_reflection_with_choice_words_is_not_a_regex_decision(tmp_path):
    agent, provider = make_agent(tmp_path, [reply("可能是你最近太闷了，在想找点变化。")], fast=True)
    result = await agent.run_natural("我为什么最近总在想要不要出门？")
    assert "变化" in result.content
    assert len(provider.calls) == 1 and agent.decision_awareness.history.list() == []


async def test_standard_awareness_does_not_preload_memory_or_agenda(tmp_path):
    agent, provider = make_agent(tmp_path, [reply("两瓶。", "PICK", agent_recommendation="两瓶")])
    retriever = SimpleNamespace(retrieve=AsyncMock(side_effect=AssertionError("preloaded memory")))
    agent.context_builder.memory_retriever = retriever
    agent.context_builder.agenda_service = SimpleNamespace(snapshot=lambda **kw: pytest.fail("preloaded agenda"))
    result = await agent.run_direct("两瓶还是三瓶？")
    assert result.content == "两瓶。" and len(provider.calls) == 1
    assert "当暗苟面临真正的选择" in provider.calls[0][0].content
    assert "classify_decision" not in str(provider.tool_schemas)
    retriever.retrieve.assert_not_awaited()


def cognition():
    return SimpleNamespace(state=lambda: SimpleNamespace(overview="最近在推进朝汐。",
        threads=[SimpleNamespace(key="project", title="项目开发", summary="今天已完成一个补丁，精力偏低。",
            status="active", manual_state="NORMAL", salience=0.9),
            SimpleNamespace(key="irrelevant", title="装修颜色", summary="UNRELATED_CANARY",
            status="active", manual_state="NORMAL", salience=1)]))


def agenda():
    from zhaoxi.agenda.models import AgendaItem, AgendaType
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    focus = AgendaItem(id="focus", type=AgendaType.FOCUS, title="今日项目主线",
        scope="today", created_at=now, updated_at=now)
    future = AgendaItem(id="future", type=AgendaType.EVENT, title="UNRELATED_FUTURE_CANARY",
        start_at=now + timedelta(days=300), created_at=now, updated_at=now)
    return SimpleNamespace(timezone=ZoneInfo("Asia/Shanghai"), list=lambda *a: [focus, future])


async def test_fast_advise_requests_only_needed_context_then_same_main_agent(tmp_path):
    question = "下午舞萌还是继续项目？"
    escalation = '[escalate:' + json.dumps({"kind":"decision", "reason":"需要今天日程与近期状态",
                                           "trigger_span":question}, ensure_ascii=False) + ']'
    agent, provider = make_agent(tmp_path, [reply(escalation),
        call("read_decision_context", query="今天下午项目安排", sources=["agenda", "current_cognition"]),
        reply("去打舞萌吧。今天主线已推进，出去缓一下更值。", "ADVISE",
              agent_recommendation="去打舞萌", predicted_user_choice="继续项目",
              context_sources=["agenda", "current_cognition"], context_refs=["agenda:focus"])], fast=True)
    agent.decision_awareness.agenda = agenda()
    agent.decision_awareness.cognition = cognition()
    result = await agent.run_natural(question)
    assert result.content.startswith("去打舞萌")
    assert len(provider.calls) == 3
    assert provider.tool_schemas[0] is None
    sources = agent.decision_awareness.diagnostics()["latest"]
    assert sources["mode"] == "ADVISE" and sources["predicted_user_choice"] != sources["agent_recommendation"]
    assert sources["context_sources"] == ["agenda", "current_cognition"]
    assert "agenda:focus" in sources["context_refs"]
    assert "current_cognition:project" in sources["context_refs"]
    tool_context = provider.calls[-1][-1].content
    assert "UNRELATED_CANARY" not in tool_context and "UNRELATED_FUTURE_CANARY" not in tool_context
    assert sum(m.role.value == "user" for m in agent.conversation.messages) == 1


@pytest.mark.parametrize("question", ["这个 Offer 接不接？", "两个正式 Offer 你直接替我决定。"])
async def test_frame_can_retrieve_facts_and_keep_final_value_conflict(tmp_path, question):
    from zhaoxi.memory.models import MemoryRecord, MemorySearchResult
    memory = MemoryRecord(id="career", content="希望工作能留出开发个人项目的时间。",
        normalized_content="career", kind="semantic", source_type="user", source="synthetic", confidence=1)
    agent, provider = make_agent(tmp_path, [
        call("read_decision_context", query="Offer 长期职业方向", sources=["memory", "principles", "current_cognition"]),
        reply("关键事实：你希望保留项目时间。真正冲突是收入和自由时间。最后得你定：愿不愿意用自由时间换收入？",
              "FRAME", agent_recommendation="先核实加班制度与合同",
              context_sources=["memory", "current_cognition", "principles"],
              context_refs=["memory:career"], guard_flags=["FAKE_GUARD"])])
    agent.decision_awareness.memory = SimpleNamespace(retrieve=AsyncMock(
        return_value=[MemorySearchResult(record=memory, score=1)]))
    agent.decision_awareness.cognition = cognition()
    result = await agent.run_direct(question)
    assert "关键事实" in result.content and "真正冲突" in result.content and "换收入" in result.content
    trace = agent.decision_awareness.diagnostics()["latest"]
    assert trace["mode"] == "FRAME" and trace["agent_recommendation"] == "先核实加班制度与合同"
    assert "memory:career" in trace["context_refs"] and trace["guard_flags"] == []
    assert len(provider.calls) == 2
    agent.decision_awareness.memory.retrieve.assert_awaited_once_with("Offer 长期职业方向")


async def test_override_is_semantic_feedback_in_same_reply_and_never_a_rule(tmp_path):
    agent, provider = make_agent(tmp_path, [reply("两瓶。", "PICK", agent_recommendation="两瓶")])
    await agent.run_direct("无糖可乐买几瓶？")
    original = agent.decision_awareness.history.list()[0]
    provider.responses.clear()
    provider.responses.append(reply("好，那就三瓶。", "NONE", feedback={
        "decision_id": original["decision_id"], "user_final_choice":"三瓶", "overridden":True}))
    result = await agent.run_direct("今天我就买三瓶。")
    assert result.content == "好，那就三瓶。"
    row = agent.decision_awareness.history.list()[0]
    assert row["overridden"] and row["user_final_choice"] == "三瓶" and row["suggestion"] == "两瓶"
    assert len(provider.calls) == 2
    assert len(agent.decision_awareness.history.list()) == 1
    assert not list((tmp_path / "choices").glob("*rule*"))


async def test_invented_feedback_and_context_receipts_are_ignored(tmp_path):
    agent, _ = make_agent(tmp_path, [reply("两瓶。", "PICK", agent_recommendation="两瓶",
        context_sources=["memory", "principles"], context_refs=["memory:invented"],
        principle_ids=["invented"], feedback={"decision_id":"other-session","user_final_choice":"三瓶"})])
    await agent.run_direct("几瓶？")
    trace = agent.decision_awareness.diagnostics()["latest"]
    assert trace["context_sources"] == trace["context_refs"] == trace["principle_ids"] == []
    assert trace["feedback"] is None


@pytest.mark.parametrize("raw", [
    '两瓶。<decision-awareness>{bad}</decision-awareness>',
    '两瓶。<decision-awareness>{"mode":"PICK"',
    '两瓶。<decision-awareness',
])
def test_malformed_sidecar_never_leaks_or_requests_another_model(raw):
    content, trace, _ = split_awareness(raw)
    assert content == "两瓶。" and trace is None


def test_cognition_is_related_summary_not_entire_journal():
    rendered = relevant_cognition(cognition(), "今天继续项目？")
    assert "精力偏低" in rendered and "UNRELATED_CANARY" not in rendered


def test_legacy_history_is_read_without_rewriting_and_corrupt_tail_is_ignored(tmp_path):
    history = ChoiceHistory(tmp_path)
    old = '{"decision_id":"old","level":"L1","summary":"活动","decision":"出门","timestamp":"2026-01-01T00:00:00+00:00"}\n'
    (tmp_path / "decision_log.jsonl").write_text(old, encoding="utf-8")
    (tmp_path / "override_log.jsonl").write_text('{"decision_id":"old","final":"继续项目"}\n', encoding="utf-8")
    (tmp_path / "choice_history.jsonl").write_text('{"broken"', encoding="utf-8")
    row = history.list()[0]
    assert row["mode"] == "ADVISE" and row["suggestion"] == "出门"
    assert row["overridden"] and row["user_final_choice"] == "继续项目"
    assert (tmp_path / "decision_log.jsonl").read_text(encoding="utf-8") == old


def test_principles_are_queryable_without_legacy_trigger(tmp_path):
    rules = RuleStore(ROOT / "data/decisions/rules")
    assert rules.get("../../.env") is None
    files = list(rules.directory.glob("*.json"))
    assert files
    original = json.loads(files[0].read_text(encoding="utf-8"))
    result = rules.retrieve_principles(original["default"])
    assert any(rule.id == original["id"] for rule in result)


async def test_future_provider_is_bounded_and_channel_independent(tmp_path):
    agent, _ = make_agent(tmp_path, [])
    provider = SimpleNamespace(retrieve=AsyncMock(return_value=[
        {"ref":"menu:1", "content":"辣椒炒肉"}, {"ref":"menu:2", "content":"面"}]))
    agent.decision_awareness.register_context_provider("menu", provider)
    result = await agent.registry.get("read_decision_context").run({"query":"吃啥", "sources":["menu"],"limit":1})
    assert len(result.data["sources"]["menu"]) == 1
    assert result.data["sources"]["menu"][0]["ref"] == "menu:1"
    provider.retrieve.assert_awaited_once_with("吃啥", limit=1)


def test_settings_default_agency_and_explicit_legacy_is_available():
    from zhaoxi.config.settings import Settings
    assert Settings(_env_file=None).decision_mode == "agency"
    assert Settings(_env_file=None, decision_mode="legacy").decision_mode == "legacy"

async def test_json_reply_and_trace_share_one_main_call(tmp_path):
    payload = {"reply":"两瓶。", "awareness":{"mode":"PICK","agent_recommendation":"两瓶"}, "escalation":None}
    agent, provider = make_agent(tmp_path, [ModelResponse(content=json.dumps(payload,ensure_ascii=False))],fast=True)
    result = await agent.run_natural("无糖可乐买几瓶？")
    assert result.content == "两瓶。" and len(provider.calls) == 1
    assert provider.tool_schemas[0] is None
    assert agent.decision_awareness.history.list()[0]["mode"] == "PICK"


async def test_partial_metadata_does_not_block_or_leak_valid_json_reply(tmp_path):
    agent, provider = make_agent(tmp_path, [ModelResponse(content='{"reply":"两瓶。","awareness":{"mode":')],fast=True)
    result = await agent.run_natural("无糖可乐买几瓶？")
    assert result.content == "两瓶。" and len(provider.calls) == 1
    assert agent.decision_awareness.history.list() == []


async def test_core_choice_scope_and_feedback_are_channel_agnostic_and_isolated(tmp_path):
    from zhaoxi.cognitive_stream.models import CognitiveEvent, CognitiveEventType
    from zhaoxi.cognitive_stream.turn import CognitiveTurnContext, set_current_turn, reset_current_turn
    agent, provider = make_agent(tmp_path, [reply("两瓶。","PICK",agent_recommendation="两瓶")])
    event = CognitiveEvent(event_type=CognitiveEventType.USER_MESSAGE,source="future_mobile",
                           channel="mobile",session_id="one",content="几瓶？")
    token = set_current_turn(CognitiveTurnContext(trigger_event=event,output_channel="mobile"))
    try:
        await agent.run_direct(event.content)
        row = agent.decision_awareness.history.list()[0]
        assert row["scope"].startswith("owner:mobile:one:")
    finally:
        reset_current_turn(token)
    event = event.model_copy(update={"session_id":"two","content":"改三瓶"})
    token = set_current_turn(CognitiveTurnContext(trigger_event=event,output_channel="mobile"))
    provider.responses.clear()
    provider.responses.append(reply("好。","NONE",feedback={
        "decision_id":row["decision_id"],"user_final_choice":"三瓶","overridden":True}))
    try:
        await agent.run_direct(event.content)
        assert agent.decision_awareness.history.list()[0]["user_final_choice"] is None
    finally:
        reset_current_turn(token)


async def test_public_context_cannot_read_or_record_owner_choices(tmp_path):
    from zhaoxi.cognitive_stream.models import CognitiveEvent, CognitiveEventType
    from zhaoxi.cognitive_stream.turn import CognitiveTurnContext, set_current_turn, reset_current_turn
    agent, _ = make_agent(tmp_path,[reply("两瓶。","PICK",agent_recommendation="两瓶")])
    event = CognitiveEvent(event_type=CognitiveEventType.USER_MESSAGE,source="group",
                           channel="future_voice",session_id="public",content="几瓶？")
    token = set_current_turn(CognitiveTurnContext(trigger_event=event,audience="public"))
    try:
        result = await agent.registry.get("read_decision_context").run({"query":"偏好","sources":["choice_history"]})
        assert not result.success and result.error == "owner_only"
        await agent.run_direct(event.content)
        with pytest.raises(PermissionError):
            agent.decision_awareness.history.list()
    finally:
        reset_current_turn(token)


def test_choice_history_is_in_configured_backup_registry(tmp_path):
    from zhaoxi.bootstrap.storage import build_data_store_specs
    from zhaoxi.config.settings import Settings
    settings = Settings(_env_file=None,decision_data_directory=str(tmp_path))
    specs = build_data_store_specs(settings,archive_enabled=False)
    choice = next(item for item in specs if item.name == "choice_history")
    assert choice.path == tmp_path / "choice_history.jsonl"

async def test_history_or_trace_failure_preserves_reply_without_extra_model(tmp_path):
    from unittest.mock import Mock
    agent, provider = make_agent(tmp_path,[reply("两瓶。","PICK",agent_recommendation="两瓶")],fast=True)
    agent.decision_awareness.history = SimpleNamespace(
        list=Mock(side_effect=OSError("unavailable")),record=Mock(side_effect=OSError("unavailable")))
    result = await agent.run_natural("几瓶？")
    assert result.content == "两瓶。" and len(provider.calls) == 1
    provider.responses.clear()
    provider.responses.append(reply("三瓶。","PICK",agent_recommendation="三瓶"))
    agent.decision_awareness.commit = Mock(side_effect=RuntimeError("optional diagnostics failure"))
    result = await agent.run_natural("几瓶？")
    assert result.content == "三瓶。" and len(provider.calls) == 2


async def test_existing_memory_tool_contributes_actual_refs(tmp_path):
    from zhaoxi.tools.base import Tool, ToolResult
    from pydantic import BaseModel
    class Query(BaseModel):
        query: str
    class Search(Tool):
        name = "search_memories"
        description = "测试查询记忆"
        input_model = Query
        persistent = True
        async def execute(self, arguments):
            return ToolResult(success=True,content="一条记忆",data=[{"id":"real","content":"更偏爱自由时间"}])
    agent, provider = make_agent(tmp_path,[
        call("search_memories",query="Offer"),
        reply("偏向 B，但你得判断时间与收入取舍。","FRAME",agent_recommendation="偏向 B")])
    agent.registry.register(Search())
    result = await agent.run_direct("Offer 怎么选？")
    assert "偏向 B" in result.content and len(provider.calls) == 2
    trace = agent.decision_awareness.diagnostics()["latest"]
    assert "memory" in trace["context_sources"] and "memory:real" in trace["context_refs"]


@pytest.mark.parametrize("invalid", [
    {"context_sources": None},
    {"context_refs": {"memory": "invented"}},
    {"agent_recommendation": "x" * 201},
    {"feedback": {"user_final_choice": "B"}},
])
async def test_invalid_optional_telemetry_preserves_valid_mode_in_same_reply(tmp_path, invalid):
    payload = {"reply": "偏向 B，但最后得你判断收入与自由时间。",
               "awareness": {"mode": "FRAME", "agent_recommendation": "偏向 B", **invalid}}
    agent, provider = make_agent(tmp_path, [ModelResponse(content=json.dumps(payload))], fast=True)
    result = await agent.run_natural("两个 Offer 怎么选？")
    assert result.content == payload["reply"] and len(provider.calls) == 1
    assert agent.decision_awareness.diagnostics()["latest"]["mode"] == "FRAME"


async def test_invalid_mode_is_not_inferred_or_reclassified(tmp_path):
    payload = {"reply": "偏向 B。", "awareness": {"mode": "not_a_mode", "context_sources": None}}
    agent, provider = make_agent(tmp_path, [ModelResponse(content=json.dumps(payload))], fast=True)
    result = await agent.run_natural("Offer 怎么选？")
    assert result.content == "偏向 B。" and len(provider.calls) == 1
    assert agent.decision_awareness.diagnostics()["latest"] is None


async def test_injected_cognition_receipt_is_recorded_when_model_omits_source(tmp_path):
    payload = {"reply": "精力偏低，先歇一下。", "awareness": {"mode": "ADVISE", "context_sources": []}}
    agent, provider = make_agent(tmp_path, [ModelResponse(content=json.dumps(payload))], fast=True)
    agent.context_builder.current_cognition_service = cognition()
    await agent.run_natural("继续项目还是休息？")
    trace = agent.decision_awareness.diagnostics()["latest"]
    assert trace["context_sources"] == ["current_cognition"]
    assert trace["context_refs"] == ["context:current_cognition"]
    assert len(provider.calls) == 1


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize(("raw", "code"), [
    (" \n\t", "empty_model_reply"),
    ('{"reply":" ","awareness":{"mode":"ADVISE"}}', "empty_model_reply"),
    ('{"reply":null,"awareness":{"mode":"ADVISE"}}', "empty_model_reply"),
    ('{"awareness":{"mode":"ADVISE"}}', "invalid_reply_protocol"),
    ('{"awareness":{"mode":', "invalid_reply_protocol"),
    ('{"reply":"未完成', "invalid_reply_protocol"),
    ('<decision-awareness>{"mode":"ADVISE"}</decision-awareness>', "empty_model_reply"),
    ('<decision-awareness>{"mode":"ADVISE"', "empty_model_reply"),
    ('[emoji:missing]<decision-awareness>{"mode":"ADVISE"}</decision-awareness>', "empty_model_reply"),
])
async def test_undeliverable_reply_fails_without_empty_bubble_choice_or_maintenance(tmp_path, fast, raw, code):
    from zhaoxi.errors import AgentLoopError
    from zhaoxi.interfaces import InterfaceGateway, InterfaceChannel, UnifiedMessage
    agent, provider = make_agent(tmp_path, [ModelResponse(content=raw)], fast=fast)
    gateway = InterfaceGateway(agent)
    with pytest.raises(AgentLoopError) as failure:
        await gateway.chat(UnifiedMessage(channel=InterfaceChannel.WEB, content="会员要不要开？", request_id="empty"))
    assert failure.value.code == code
    assert agent.last_action_trace["response_status"] == "failed"
    assert agent.last_reply_protocol["status"] == "failed"
    assert agent.last_reply_protocol["error_code"] == code
    assert all(m.role.value == "user" for m in agent.conversation.messages)
    assert agent.decision_awareness.history.list() == []
    assert gateway._maintenance is None and len(provider.calls) == 1
    assert "empty" not in gateway._responses
    # The accepted user turn remains; the existing resume route delivers a fresh reply.
    provider.responses.clear()
    provider.responses.append(reply("先不开，等真需要同步再买。", "ADVISE", agent_recommendation="先不开"))
    retry = await gateway.regenerate(agent.conversation.messages[-1].message_id, request_id="retry")
    assert retry.content.startswith("先不开")
    assert sum(m.role.value == "user" for m in agent.conversation.messages) == 1
    assert len(agent.decision_awareness.history.list()) == 1
    if gateway._maintenance and gateway._maintenance.worker:
        await gateway._maintenance.worker


async def test_picture_choice_uses_previous_dialogue_and_records_actual_image(tmp_path):
    agent, provider = make_agent(tmp_path, [ModelResponse(content=json.dumps({
        "reply": "如果只是单机阅读，先不开；需要同步再试年费。",
        "awareness": {"mode": "ADVISE", "agent_recommendation": "单机阅读先不开"}}, ensure_ascii=False))])
    agent.conversation.add_user("平常只在这个阅读器上看书。")
    agent.conversation.add_assistant("好，我会把单机阅读这一点带上。")
    result = await agent.run("会员要不要开，开哪档？", images=["data:image/png;base64,AAAA"])
    assert result.content.startswith("如果只是单机阅读") and len(provider.calls) == 1
    assert any(m.content == "平常只在这个阅读器上看书。" for m in provider.calls[0])
    assert provider.calls[0][-1].images
    trace = agent.decision_awareness.diagnostics()["latest"]
    assert trace["mode"] == "ADVISE" and "current_image" in trace["context_sources"]
    assert any(ref.startswith("image:") for ref in trace["context_refs"])
    assert agent.last_reply_protocol["body_chars"] > 0 and agent.last_reply_protocol["awareness"] == "valid"


async def test_invalid_awareness_preserves_valid_body_without_extra_model(tmp_path):
    agent, provider = make_agent(tmp_path, [ModelResponse(content='{"reply":"先不开。","awareness":{"mode":"UNKNOWN"}}')])
    result = await agent.run_direct("会员要不要开？")
    assert result.content == "先不开。" and len(provider.calls) == 1
    assert agent.decision_awareness.history.list() == []
    assert agent.last_reply_protocol["awareness"] == "invalid"
    assert "reply" not in result.content and "UNKNOWN" not in result.content
