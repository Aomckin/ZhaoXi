"""User-reported v1.4.8 failures, isolated from production state and networks."""
import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from conftest import FakeProvider
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.core.message import Message, Role
from zhaoxi.tools.registry import ToolRegistry
from zhaoxi.tools.domain_map import domain_prompt, tool_domain_map
from zhaoxi.models.types import ModelResponse
from zhaoxi.interfaces import InterfaceGateway, UnifiedMessage, InterfaceChannel
from zhaoxi.session.sqlite import SQLiteSessionStore
from zhaoxi.session.base import Session
from zhaoxi.cognitive_stream import ExperienceStream
from zhaoxi.cognitive_stream.models import CognitiveEvent, CognitiveEventType
from zhaoxi.cognitive_stream.turn import CognitiveTurnContext, current_turn, set_current_turn, reset_current_turn
from zhaoxi.tools.builtin.save_emoji import SaveEmojiTool
from zhaoxi.errors import AgentLoopError, ProviderError


def agent(provider, **kwargs):
    return ZhaoxiAgent(provider=provider, registry=ToolRegistry(), context_builder=ContextBuilder("朝汐"), **kwargs)


async def test_full_ui_history_survives_short_window_and_restart(tmp_path):
    store = SQLiteSessionStore(tmp_path / "session.db", max_messages=4)
    conversation = Conversation(max_messages=4)
    session = Session(id="local", conversation=conversation)
    identities = []
    for index in range(6):
        user = conversation.add_user(f"user-{index}")
        user.metadata = {"event_id": f"event-{index}", "request_id": f"request-{index}", "private_context": "must-not-persist"}
        identities += [user.message_id, conversation.add_assistant(f"assistant-{index}").message_id]
        await store.save(session)
    restarted = SQLiteSessionStore(store.path, max_messages=4)
    latest = await restarted.get("local")
    assert len(latest.conversation.messages) == 4
    page = await restarted.history_page("local", limit=3)
    middle = await restarted.history_page("local", before=page["before"], limit=3)
    first = await restarted.history_page("local", before=middle["before"], limit=3)
    all_messages = first["messages"] + middle["messages"] + page["messages"] + latest.conversation.messages
    assert [m.message_id for m in all_messages] == identities
    assert [m.content for m in all_messages][::2] == [f"user-{i}" for i in range(6)]
    assert all("private_context" not in m.metadata for m in all_messages)
    assert all_messages[0].metadata["event_id"] == "event-0"
    await restarted.delete("local")
    assert not (await restarted.history_page("local"))["messages"]


async def test_regenerate_preserves_identity_before_model_and_does_not_ingest_again(tmp_path):
    seen = []
    class Recording(FakeProvider):
        async def generate(self, messages, *args, **kwargs):
            turn = current_turn()
            seen.append((turn.trigger_event.event_id, [(m.message_id, m.timestamp) for m in core.conversation.messages if m.role == Role.USER]))
            return await super().generate(messages, *args, **kwargs)
    provider = Recording([ModelResponse(content="first"), ModelResponse(content="retry")])
    core = agent(provider)
    core.experience_stream = ExperienceStream(tmp_path / "events.db")
    from zhaoxi.cognitive_stream.ingress import CognitiveIngress
    core.cognitive_ingress = CognitiveIngress(core.experience_stream)
    gateway = InterfaceGateway(core)
    notifications = []
    gateway.reply_notifier = lambda *args: notifications.append(args)
    request = UnifiedMessage(request_id="original", channel=InterfaceChannel.WEB, content="这张图")
    first = await gateway.chat(request)
    before = [e.event_id for e in core.experience_stream.recent(200) if e.event_type == CognitiveEventType.USER_MESSAGE]
    await gateway.chat(request)
    assert len(notifications) == 1
    retried = await gateway.regenerate(first.message_id, request_id="retry")
    assert retried.content == "retry"
    again = await gateway.regenerate(first.message_id, request_id="retry")
    assert again.message_id == retried.message_id and len(provider.calls) == 2
    assert seen[0] == seen[1]
    assert before == [e.event_id for e in core.experience_stream.recent(200) if e.event_type == CognitiveEventType.USER_MESSAGE]
    assert len(notifications) == 2


@pytest.mark.parametrize("images,reference,expected", [
    (("data:image/png;base64,current",), "latest", "data:image/png;base64,current"),
    (("data:image/png;base64,first", "data:image/png;base64,second"), "latest", None),
    (("data:image/png;base64,first", "data:image/png;base64,second"), "latest:1", "data:image/png;base64,second"),
    ((), "latest", None),
])
def test_image_latest_binds_current_source_and_refuses_ambiguity(images, reference, expected):
    conversation = Conversation()
    conversation.add_user("old desktop screenshot", images=["data:image/png;base64,wrong"])
    tool = SaveEmojiTool(Mock(), conversation)
    trigger = CognitiveEvent(event_type=CognitiveEventType.EXTERNAL_MESSAGE, source="qq", content="存这张")
    token = set_current_turn(CognitiveTurnContext(trigger_event=trigger, images=images))
    try:
        assert tool._resolve(reference) == expected
    finally:
        reset_current_turn(token)


def test_new_domain_and_changed_manifest_are_discovered_without_name_table():
    rows = [{"name":"unseen_tool", "group":"unseen_group", "domain":"植物园", "domain_description":"管理植物养护", "domain_boundaries":"不代替财务记录", "enabled":True,"available":True}]
    prompt = domain_prompt(rows)
    assert "植物园" in prompt and "管理植物养护" in prompt and "不代替财务记录" in prompt
    rows[0]["enabled"] = False
    assert tool_domain_map(rows)[0]["usable"] == 0
    assert '"usable":0' in domain_prompt(rows)


@pytest.mark.parametrize("kind", ["CORRECTION", "CONTINUATION", "EXECUTION", "NONE", None])
async def test_non_new_decision_does_not_create_choice_history(tmp_path, kind):
    from zhaoxi.decision.history import ChoiceHistory
    payload = {"reply":"明白了", "awareness":{"mode":"ADVISE","decision_kind":kind,"decision_question":"投递节奏应如何安排？","agent_recommendation":"按周安排"}}
    core = agent(FakeProvider([ModelResponse(content=json.dumps(payload, ensure_ascii=False))]), decision_mode="agency")
    core.decision_awareness.history = ChoiceHistory(tmp_path / "decisions")
    await core.run_natural("填表已经有对应的东西了")
    assert core.decision_awareness.history.list() == []


async def test_new_decision_records_standalone_question_without_extra_model(tmp_path):
    from zhaoxi.decision.history import ChoiceHistory
    question = "在每周留一天测评跟进的约束下，官网投递应按每天25—30份还是按每周120—150份安排？"
    provider = FakeProvider([ModelResponse(content=json.dumps({"reply":"按周安排", "awareness":{"mode":"ADVISE","decision_kind":"NEW","decision_question":question}}, ensure_ascii=False))])
    core = agent(provider, decision_mode="agency")
    core.decision_awareness.history = ChoiceHistory(tmp_path / "choices")
    await core.run_natural("可以的话，我打算之后一天投25到30个")
    row = core.decision_awareness.history.list()[0]
    assert row["summary"] == question == row["decision_question"]
    assert len(provider.calls) == 1


async def test_timeout_reports_specific_code():
    class Slow(FakeProvider):
        async def generate(self, *args, **kwargs):
            await asyncio.sleep(1)
    core = agent(Slow([]), timeout_seconds=.01)
    with pytest.raises(AgentLoopError) as failed:
        await core.run_natural("慢请求")
    assert failed.value.code == "agent_timeout"


async def test_consolidation_disabled_not_due_and_provider_failure_are_distinct():
    from zhaoxi.memory.consolidation import AutoConsolidator, AutoConsolidationConfig
    repository = SimpleNamespace(set_runtime=AsyncMock(), get_runtime=AsyncMock(side_effect=["0", datetime.now(UTC).isoformat()]))
    service = SimpleNamespace(repository=repository)
    disabled = AutoConsolidator(FakeProvider([]), service, AutoConsolidationConfig(enabled=False))
    assert (await disabled.run_result()).reason == "disabled"
    enabled = AutoConsolidator(FakeProvider([]), service)
    assert (await enabled.run_result()).reason == "not_due"
    enabled._run_result = AsyncMock(side_effect=ProviderError("offline", code="provider_unreachable"))
    outcome = await enabled.run_result()
    assert outcome.status == "FAILED" and outcome.error_code == "provider_unreachable"


def test_background_notification_dedupes_sound_and_foreground_is_quiet(monkeypatch):
    from zhaoxi.desktop.notifications import NativeNotifier
    sound = Mock()
    monkeypatch.setitem(__import__('sys').modules, "winsound", SimpleNamespace(PlaySound=sound,SND_FILENAME=1,SND_ASYNC=2,SND_NODEFAULT=4))
    window = SimpleNamespace(focused=Mock(return_value=True), _native=None)
    notifier = NativeNotifier(window, Mock(), system_mode=True)
    notifier._fallback = SimpleNamespace(show=Mock())
    notifier.show("reply", "text", "id")
    sound.assert_not_called()
    window.focused.return_value = False
    notifier.show("reply", "text", "id")
    notifier.show("reply", "text", "id")
    sound.assert_called_once()
    notifier._fallback.show.assert_called_once()


def test_workflow_management_persists_disable_delete_and_new_domain(tmp_path):
    from zhaoxi.workflow.registry import WorkflowRegistry
    from zhaoxi.workflow.models import WorkflowDefinition
    path = tmp_path / "management.json"
    definition = WorkflowDefinition(id="new-flow",version=1,name="新流程",steps=[{"id":"done","type":"end"}])
    registry = WorkflowRegistry()
    registry.configure_management(path)
    registry.manage(definition.id, definition)
    registry.manage(definition.id, definition.model_copy(update={"enabled":False}))
    reopened = WorkflowRegistry();reopened.configure_management(path)
    assert reopened.catalog()[0]["enabled"] is False
    reopened.manage(definition.id)
    latest = WorkflowRegistry();latest.configure_management(path)
    assert latest.catalog() == []


async def test_disabled_workflow_is_rejected_even_in_router_fallback(tmp_path):
    from zhaoxi.cognitive.router import CognitiveRouter, CognitiveRoute
    router = CognitiveRouter(FakeProvider([]),
        routing_hints=[{"route":"workflow","markers":["启动流程"],"workflow_id":"old-demo"}],
        workflow_catalog_provider=lambda:[{"id":"old-demo","enabled":False,"available":False}])
    route = await router.route("启动流程")
    assert route.route == CognitiveRoute.TOOL and route.workflow_id is None


async def test_action_sidecar_prompt_available_without_extra_interim_tool_schema():
    from zhaoxi.models.types import ToolCall
    from zhaoxi.config.settings import Settings
    provider = FakeProvider([
        ModelResponse(tool_calls=[ToolCall(id="catalog",name="inspect_tool_catalog",arguments={"action":"summary"})]),
        ModelResponse(tool_calls=[ToolCall(id="interim",name="emit_interim_reply",arguments={"content":"先把线索对一下"})]),
        ModelResponse(content="done")])
    core = agent(provider);core.settings = Settings(_env_file=None, interim_reply_threshold_seconds=1000)
    gateway = InterfaceGateway(core);events=[];gateway.event_sink=events.append
    await gateway.chat(UnifiedMessage(request_id="before-threshold",channel=InterfaceChannel.WEB,content="检查工具后整理"))
    assert not any(s["function"]["name"] == "emit_interim_reply" for s in provider.tool_schemas[1])
    assert "同一次 response.content" in provider.calls[1][0].content
    assert not any(e["type"] == "interim_reply" for e in events)
    assert any(e.get("event",{}).get("event_type") == "interim_response_skipped" for e in events)


async def test_consolidation_apply_failure_does_not_advance_success_checkpoint():
    from zhaoxi.memory.consolidation import AutoConsolidator, ConsolidationCandidate, AutoConsolidationConfig
    repository = SimpleNamespace(set_runtime=AsyncMock(), get_runtime=AsyncMock(side_effect=["25", None]))
    service = SimpleNamespace(repository=repository, _increment_runtime=AsyncMock(), consolidate=AsyncMock(side_effect=RuntimeError("storage failed")))
    provider = FakeProvider([ModelResponse(content=json.dumps({"decisions":[{"cluster_id":"cluster","action":"create_semantic","content":"stable fact","evidence_memory_ids":["1","2"]}]}))])
    worker = AutoConsolidator(provider, service, AutoConsolidationConfig(min_evidence=2))
    worker.prefilter = AsyncMock(return_value=[ConsolidationCandidate(cluster_id="cluster",topic="topic",recent_episode_ids=["1","2"],existing_semantic_ids=[],time_range=[],member_count=2,representative_memories=[])])
    with pytest.raises(RuntimeError):
        await worker.run_result()
    assert all(call.args[0] != "last_consolidation_check_at" for call in repository.set_runtime.call_args_list)


async def test_direct_router_hint_cannot_reenable_disabled_workflow():
    from zhaoxi.cognitive.router import CognitiveRouter, CognitiveRoute
    from zhaoxi.models.types import ToolCall
    provider = FakeProvider([ModelResponse(tool_calls=[ToolCall(id="route",name="route_cognition",arguments={"route":"direct","reason":"simple"})])])
    router = CognitiveRouter(provider, routing_hints=[{"route":"workflow","markers":["启动流程"],"workflow_id":"old-demo"}],
        workflow_catalog_provider=lambda:[{"id":"old-demo","enabled":False,"available":False}])
    result = await router.route("启动流程")
    assert result.route == CognitiveRoute.TOOL and result.workflow_id is None
