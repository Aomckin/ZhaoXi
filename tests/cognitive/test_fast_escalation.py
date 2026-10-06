"""One-way capability discovery before a FAST draft becomes user-visible."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel
from conftest import FakeProvider
from zhaoxi.cognitive.coordinator import CognitiveCoordinator
from zhaoxi.cognitive.fast_gate import FastDialogueGate
from zhaoxi.cognitive.memory_decision import MemoryAction
from zhaoxi.cognitive.router import CognitiveRouter, CognitiveRoute
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.fast_chat import FastChatRuntime, FastEscalationKind
from zhaoxi.decision.service import DecisionService
from zhaoxi.errors import ProviderError, AgentLoopError
from zhaoxi.interfaces.gateway import InterfaceGateway
from zhaoxi.interfaces.models import UnifiedMessage, InterfaceChannel
from zhaoxi.memory.models import MemoryRecord, MemorySearchResult
from zhaoxi.memory.retrieval import MemoryRetriever
from zhaoxi.models.resilient import ResilientProvider
from zhaoxi.models.types import ModelResponse, ToolCall
from zhaoxi.permission.models import PermissionLevel, SideEffect
from zhaoxi.session.base import Session
from zhaoxi.session.sqlite import SQLiteSessionStore
from zhaoxi.tools.base import Tool, ToolResult
from zhaoxi.tools.builtin import create_builtin_tools
from zhaoxi.tools.registry import ToolRegistry


def call(name, arguments=None):
    return ModelResponse(tool_calls=[ToolCall(id=name, name=name, arguments=arguments or {})])


def make_agent(responses):
    inner = FakeProvider(responses)
    provider = ResilientProvider([inner])
    registry = ToolRegistry()
    for tool in create_builtin_tools():
        registry.register(tool)
    agent = ZhaoxiAgent(provider=provider, registry=registry, context_builder=ContextBuilder("朝汐"))
    agent.cognitive = CognitiveCoordinator(agent=agent, router=CognitiveRouter(provider),
                                            fast_gate=FastDialogueGate())
    agent.cognitive.force_fast_chat = True
    return agent, inner


@pytest.mark.parametrize(("draft", "kind"), [
    ("[escalate:tool]", FastEscalationKind.TOOL),
    ("这段必须丢弃 [escalate:recall] 后半段也不能出现", FastEscalationKind.RECALL),
    ("[ESCALATE:DECISION]", FastEscalationKind.DECISION),
    ("[escalate:unknown]", FastEscalationKind.STANDARD),
    ("[escalate:", FastEscalationKind.STANDARD),
    ("[escalate tool]", FastEscalationKind.STANDARD),
    ("【escalate:recall】", FastEscalationKind.RECALL),
])
def test_explicit_capability_and_malformed_directives_are_private(draft, kind):
    assert FastChatRuntime.escalation_request(draft) is kind
    assert FastChatRuntime.escalation_request("在呢，刚才那个界面确实有点怪。") is None


async def test_tool_upgrade_has_one_fast_attempt_and_no_router_or_draft_leak(tmp_path):
    draft = "草稿污染：我已经替你保存了。 [escalate:tool]"
    agent, inner = make_agent([ModelResponse(content=draft), call("current_time"),
                               ModelResponse(content="标准通道核验完成。")])
    agent.cognitive.router.route = AsyncMock(side_effect=AssertionError("must not re-enter Router"))
    auto_memory = SimpleNamespace(process=AsyncMock(return_value=SimpleNamespace(action=MemoryAction.IGNORE)))
    agent.cognitive.auto_memory = auto_memory
    agent.session_record = Session()
    agent.session_store = SQLiteSessionStore(tmp_path / "sessions.db")
    gateway = InterfaceGateway(agent)
    events = []
    gateway.event_sink = events.append
    result = await gateway.chat(UnifiedMessage(channel=InterfaceChannel.WEB, content="请查询当前时间"))
    stored = await agent.session_store.get(agent.session_record.id)
    assert result.content == "标准通道核验完成。"
    assert len(inner.calls) == 3 and inner.tool_schemas[0] is None
    agent.cognitive.router.route.assert_not_awaited()
    assert sum("当前处于 FAST_CHAT" in (c[0].content or "") for c in inner.calls) == 1
    assert sum(m.role.value == "user" for m in stored.conversation.messages) == 1
    for value in (events, result.model_dump(mode="json"), [m.model_dump(mode="json") for m in stored.conversation.messages]):
        text = json.dumps(value, ensure_ascii=False)
        assert "草稿污染" not in text and "[escalate:" not in text
    auto_memory.process.assert_awaited_once_with("请查询当前时间", result.content)
    metrics = agent.last_action_trace["runtime_metrics"]
    assert metrics["fast_escalation_count"] == 1
    assert metrics["fast_escalation_kind"] == "tool"
    assert metrics["runtime_lane"] == "standard"
    assert metrics["router_llm_calls"] == 0
    assert not any(e.get("type") == "interim_reply" for e in events)


async def test_recall_upgrade_loads_true_memory_only_after_fast_draft():
    agent, inner = make_agent([ModelResponse(content="[escalate:recall]"),
                               ModelResponse(content="当时那条记忆里写的是蓝色。")])
    record = MemoryRecord(kind="episodic", content="上次确定的物品是蓝色。", normalized_content="blue",
                          source_type="user", source="synthetic", confidence=1)
    async def retrieve(query):
        assert len(inner.calls) == 1
        return [MemorySearchResult(record=record, score=1)]
    retriever = MemoryRetriever(SimpleNamespace())
    retriever.retrieve = AsyncMock(side_effect=retrieve)
    agent.context_builder.memory_retriever = retriever
    gateway = InterfaceGateway(agent)
    result = await gateway.chat(UnifiedMessage(channel=InterfaceChannel.WEB, content="还记得上次具体说过什么吗？"))
    retriever.retrieve.assert_awaited_once_with("还记得上次具体说过什么吗？")
    assert record.content not in inner.calls[0][0].content
    assert record.content in inner.calls[1][0].content
    assert len(inner.calls) == 2
    assert result.content == "当时那条记忆里写的是蓝色。"
    assert agent.last_action_trace["runtime_metrics"]["fast_escalation_kind"] == "recall"


@pytest.mark.parametrize("via_router", [False, True])
async def test_decision_upgrade_reaches_guarded_decision_service_once(tmp_path, via_router):
    responses = ([call("route_cognition", {"route":"fast_chat", "reason":"ordinary chat"})] if via_router else [])
    responses += [ModelResponse(content="草稿中的选项不能作为判断依据 [escalate:decision]"),
        call("classify_decision", {"level":"L1", "domain":"general", "decision":"今天先休息",
                                  "reasons":["测试确认的理由"]}),
        call("select_decision_expression", {"tone":"plain", "reason_indices":[0]})]
    agent, inner = make_agent(responses)
    if via_router:
        agent.cognitive.force_fast_chat = False
        from zhaoxi.cognitive.fast_gate import FastDialogueDecision, FastGateLane
        agent.cognitive.fast_gate.decide = lambda *a, **kw: FastDialogueDecision(lane=FastGateLane.AMBIGUOUS,reason="test")
    service = DecisionService(agent.provider,
        rule_directory=Path(__file__).resolve().parents[2] / "data/decisions/rules", data_directory=tmp_path)
    agent.decision_service = service
    service.evaluate = AsyncMock(wraps=service.evaluate)
    result = await agent.run_natural("之前那个我该怎么选？")
    assert result.route is CognitiveRoute.DIRECT
    assert service.last_triggered and service.last_result is not None
    service.evaluate.assert_awaited_once()
    assert service.evaluate.call_args.kwargs["planner_requested"] is True
    assert len(inner.calls) == 3 + int(via_router)
    assert sum("当前处于 FAST_CHAT" in (c[0].content or "") for c in inner.calls) == 1
    assert all("草稿中的选项" not in (m.content or "") for c in inner.calls[1+int(via_router):] for m in c)
    assert "[escalate:" not in result.content
    assert sum(m.role.value == "user" for m in agent.conversation.messages) == 1


async def test_upgrade_without_decision_service_stays_standard():
    agent, inner = make_agent([ModelResponse(content="[escalate:decision]"), ModelResponse(content="需要先确认你的关键条件。")])
    result = await agent.run_natural("我该怎么选？")
    assert result.route is CognitiveRoute.DIRECT and len(inner.calls) == 2
    assert "当前处于 FAST_CHAT" not in inner.calls[1][0].content


class WriteInput(BaseModel):
    content: str


class GuardedWrite(Tool):
    name = "guarded_write"
    description = "写入受控验收记录"
    group = "filesystem_write"
    input_model = WriteInput
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.LOCAL_STATE})
    def __init__(self):
        self.executions = []
    async def execute(self, arguments):
        self.executions.append(arguments.content)
        return ToolResult(success=True, content="saved")


async def test_native_call_draft_is_discarded_and_standard_keeps_permission_guard():
    agent, inner = make_agent([
        ModelResponse(content="原生调用草稿不得显示", tool_calls=[ToolCall(id="discarded", name="guarded_write", arguments={"content":"discarded args"})]),
        call("guarded_write", {"content":"standard args"}),
    ])
    tool = agent.registry.register(GuardedWrite())
    result = await agent.run_natural("请写入受控记录")
    assert result.route is CognitiveRoute.TOOL and result.permission_confirmation is not None
    assert tool.executions == [] and len(inner.calls) == 2
    assert result.permission_confirmation.request.arguments == {"content":"standard args"}
    assert all("discarded args" not in json.dumps(m.model_dump(mode="json")) for m in agent.conversation.messages)
    assert "原生调用草稿" not in result.content


async def test_failed_standard_reply_never_publishes_discarded_draft():
    agent, inner = make_agent([ModelResponse(content="失败也不能泄漏的草稿 [escalate:recall]")])
    original = agent.provider.generate
    async def fail_standard(messages, tools=None, **kwargs):
        if "当前处于 FAST_CHAT" not in messages[0].content:
            raise ProviderError("test unavailable", code="provider_http_503")
        return await original(messages, tools, **kwargs)
    agent.provider.generate = fail_standard
    gateway = InterfaceGateway(agent)
    events = []
    gateway.event_sink = events.append
    with pytest.raises(AgentLoopError, match="模型服务当前不可访问"):
        await gateway.chat(UnifiedMessage(channel=InterfaceChannel.WEB, content="还记得上次说过什么吗？"))
    assert all("失败也不能泄漏" not in (m.content or "") for m in agent.conversation.messages)
    assert "失败也不能泄漏" not in json.dumps(events, ensure_ascii=False)
    assert not any(m.role.value == "assistant" for m in agent.conversation.messages)
    assert len(inner.calls) == 1


class LookupInput(BaseModel):
    query: str


class RepairLookup(Tool):
    name = "repair_lookup"
    description = "查找隔离验收记录的 ID"
    group = "filesystem_write"
    input_model = LookupInput

    def __init__(self):
        self.calls = []

    async def execute(self, arguments):
        self.calls.append(arguments.query)
        return ToolResult(success=True, content="记录 ID 为 fixture-7", data={"id": "fixture-7"})


async def test_fast_upgrade_discovers_reads_then_writes_once_with_default_guards():
    from dataclasses import replace
    agent, provider = make_agent([
        ModelResponse(content="[escalate:tool]"),
        call("request_tool_group", {"group": "filesystem_write"}),
        call("repair_lookup", {"query": "隔离记录"}),
        call("guarded_write", {"content": "fixture-7"}),
        ModelResponse(content="记录已保存。"),
    ])
    reader = agent.registry.register(RepairLookup())
    writer = agent.registry.register(GuardedWrite())
    original = agent._tool_context
    agent._tool_context = lambda intent: replace(original(intent), exposed_tools=())
    gateway = InterfaceGateway(agent)
    pending = await gateway.chat(UnifiedMessage(channel=InterfaceChannel.WEB, content="请查询记录 ID 再写入记录"))
    assert pending.status == "waiting_for_permission" and writer.executions == []
    assert reader.calls == ["隔离记录"]
    before = agent.last_action_trace["runtime_metrics"]
    assert before["discovery_round"] == 1 and before["standard_model_round"] == 3
    assert len(provider.calls) == 4 and not agent.allow_multi_model_calls
    completed = await gateway.resolve_permission(pending.permission.confirmation_id, approve=True, request_id="repair-confirm")
    assert completed.status == "completed" and writer.executions == ["fixture-7"]
    assert reader.calls == ["隔离记录"] and len(provider.calls) == 5
    assert provider.tool_schemas[-1] is None
    assert sum("当前处于 FAST_CHAT" in (messages[0].content or "") for messages in provider.calls) == 1


def unexecuted_agent():
    return make_agent([ModelResponse(content="[escalate:tool]"),
                       *[ModelResponse(content="已经保存成功。") for _ in range(3)]])


async def test_explicit_retry_restores_unexecuted_task_without_fast_or_false_completion():
    agent, provider = unexecuted_agent()
    gateway = InterfaceGateway(agent)
    events = []
    gateway.event_sink = events.append
    failed = await gateway.chat(UnifiedMessage(channel=InterfaceChannel.WEB, content="请查询当前时间"))
    assert failed.status == "failed" and "已经保存成功" not in failed.content
    assert "未完成任何工具操作" in failed.content
    assert failed.activity["result_status"] == "failed"
    assert agent.last_action_trace["runtime_metrics"]["result_status"] == "failed"
    assert agent.tool_retry_context is not None
    previous = agent.tool_retry_context.request_id
    provider.responses.clear()
    provider.responses.extend([call("current_time"), ModelResponse(content="已核验时间。")])
    agent.cognitive.router.route = AsyncMock(side_effect=AssertionError("retry must not re-enter Router"))
    retried = await gateway.chat(UnifiedMessage(channel=InterfaceChannel.WEB,
                                content="你现在再试一次，这个我可不想自己写。"))
    assert retried.status == "completed" and retried.content == "已核验时间。"
    assert agent.tool_retry_context is None
    assert len(provider.calls) == 5 and provider.tool_schemas[-2]
    assert "原始请求为" in provider.calls[-2][0].content and "请查询当前时间" in provider.calls[-2][0].content
    assert [m.content for m in agent.conversation.messages if m.role.value == "user"] == [
        "请查询当前时间", "你现在再试一次，这个我可不想自己写。"]
    resumed = next(e["event"] for e in events if e.get("type") == "agent_event"
                   and e["event"]["event_type"] == "tool_retry_resumed")
    assert resumed["metadata"]["previous_request_id"] == previous


@pytest.mark.parametrize("change", ["channel", "session", "expired", "cancel", "quoted", "expanded"])
async def test_retry_scope_cannot_be_borrowed_or_extended(change):
    from dataclasses import replace
    from zhaoxi.core.tool_retry import RETRY_TTL_SECONDS
    agent, provider = unexecuted_agent()
    gateway = InterfaceGateway(agent)
    await gateway.chat(UnifiedMessage(channel=InterfaceChannel.WEB, content="请查询当前时间"))
    assert agent.tool_retry_context
    text = {"cancel": "不用重试了", "quoted": "只是引用“再试一次”", "expanded": "再试一次，把另外的文件删了"}.get(change, "再试一次")
    if change == "expired":
        agent.tool_retry_context = replace(agent.tool_retry_context,
            created_at=agent.tool_retry_context.created_at - RETRY_TTL_SECONDS - 1)
    provider.responses.clear()
    provider.responses.append(ModelResponse(content="收到。"))
    result = await gateway.chat(UnifiedMessage(channel=InterfaceChannel.CLI if change == "channel" else InterfaceChannel.WEB,
        session_id="another-session" if change == "session" else "local", content=text))
    assert agent.tool_retry_context is None
    assert agent.last_action_trace["runtime_metrics"]["route_source"] != "scoped_tool_retry"
    assert not result.permission and result.activity["result_status"] == "completed"


@pytest.mark.parametrize("result_kind", ["completed", "unknown", "denied", "failed_write"])
async def test_attempted_write_does_not_create_retry_context(result_kind):
    class ResultWrite(GuardedWrite):
        async def execute(self, arguments):
            self.executions.append(arguments.content)
            return ToolResult(success=result_kind == "completed", content="隔离结果",
                              error=None if result_kind == "completed" else "write_failed",
                              metadata={"unknown_outcome": result_kind == "unknown"})
    agent, provider = make_agent([ModelResponse(content="[escalate:tool]"),
        call("guarded_write", {"content": "one"}), ModelResponse(content="如实说明结果。")])
    writer = agent.registry.register(ResultWrite())
    agent.registry.update_tools(name=writer.name, confirm_write=False)
    gateway = InterfaceGateway(agent)
    if result_kind == "denied":
        agent.registry.update_tools(name=writer.name, confirm_write=True)
        pending = await gateway.chat(UnifiedMessage(channel=InterfaceChannel.WEB, content="请写入受控记录"))
        await gateway.resolve_permission(pending.permission.confirmation_id, approve=False, request_id="repair-decline")
    else:
        await gateway.chat(UnifiedMessage(channel=InterfaceChannel.WEB, content="请写入受控记录"))
    assert agent.tool_retry_context is None
    provider.responses.clear()
    provider.responses.append(ModelResponse(content="收到。"))
    before = len(writer.executions)
    await gateway.chat(UnifiedMessage(channel=InterfaceChannel.WEB, content="再试一次"))
    assert len(writer.executions) == before
    assert agent.last_action_trace["runtime_metrics"]["route_source"] != "scoped_tool_retry"


async def test_productive_discovery_credit_does_not_consume_final_step_with_another_action():
    agent, provider = make_agent([ModelResponse(content="[escalate:tool]"),
        call("request_tool_group", {"group": "filesystem_write"}),
        call("repair_lookup", {"query": "one"}),
        call("guarded_write", {"content": "must not execute"})])
    agent.max_steps = 3
    reader = agent.registry.register(RepairLookup())
    writer = agent.registry.register(GuardedWrite())
    gateway = InterfaceGateway(agent)
    result = await gateway.chat(UnifiedMessage(channel=InterfaceChannel.WEB, content="请查询记录 ID 再写入记录"))
    assert result.status == "partial" and not result.permission
    assert reader.calls == ["one"] and not writer.executions
    assert len(provider.calls) == 4 and provider.tool_schemas[-1] is None


async def test_restored_unexecuted_write_still_requires_new_confirmation():
    agent, provider = unexecuted_agent()
    writer = agent.registry.register(GuardedWrite())
    gateway = InterfaceGateway(agent)
    await gateway.chat(UnifiedMessage(channel=InterfaceChannel.WEB, content="请写入受控记录"))
    assert agent.tool_retry_context
    provider.responses.clear()
    provider.responses.extend([call("guarded_write", {"content": "newly validated"}), ModelResponse(content="写入已确认。")])
    result = await gateway.chat(UnifiedMessage(channel=InterfaceChannel.WEB, content="再试一次"))
    assert result.status == "waiting_for_permission" and writer.executions == []
    assert agent.tool_retry_context is None
    await gateway.resolve_permission(result.permission.confirmation_id, approve=True, request_id="retry-write-confirm")
    assert writer.executions == ["newly validated"]
