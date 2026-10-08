"""Runtime regression cases A-H: evidence, bounded repair and honest closing."""
import json
from types import SimpleNamespace
import pytest
from pydantic import BaseModel
from conftest import FakeProvider
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.fast_chat import FastChatRuntime
from zhaoxi.core.loop_safety import LoopSafety,failure_fingerprint
from zhaoxi.models.types import ModelResponse,ToolCall
from zhaoxi.tools.base import Tool,ToolResult
from zhaoxi.tools.registry import ToolRegistry
from zhaoxi.reliability import CorrelationContext,correlation_scope
from zhaoxi.observability import action_trace_scope
from zhaoxi.reliability.retry import BudgetPolicy,provider_budget_scope,record_provider_tokens,BudgetState

@pytest.fixture(autouse=True)
def correlation():
    with correlation_scope(CorrelationContext(trace_id="loop-safety",request_id="loop-safety")):
        yield

class Input(BaseModel):
    query: str

class Probe(Tool):
    name="probe"
    description="只读验收工具"
    input_model=Input
    def __init__(self,results):self.results=results;self.calls=[]
    async def execute(self,args):
        self.calls.append(args.query)
        return self.results[min(len(self.calls)-1,len(self.results)-1)]

def call(name="probe",query="q",id="call"):
    return ModelResponse(tool_calls=[ToolCall(id=id,name=name,arguments={"query":query})])

def agent(responses,tool=None):
    registry=ToolRegistry();registry.register(tool or Probe([ToolResult(success=True,content="事实",data={"value":1})]))
    provider=FakeProvider(responses)
    return ZhaoxiAgent(provider=provider,registry=registry,context_builder=ContextBuilder("朝汐")),provider


def escalation(span,kind="tool"):
    return "[escalate:"+json.dumps({"kind":kind,"reason":"本轮需求","trigger_span":span},ensure_ascii=False)+"]"


@pytest.mark.parametrize("draft",[escalation("台账补一下"),"[escalate:tool]","我这就查询台账。"])
async def test_fast_escalation_cannot_be_triggered_by_history_only(draft):
    a,p=agent([ModelResponse(content=draft),ModelResponse(content="在呢。")])
    a.conversation.add_assistant("台账先挂着，什么时候想补喊我。")
    with action_trace_scope() as trace:
        result=await FastChatRuntime(a).run_fast_chat("小金毛")
        assert not result.escalated and result.content=="在呢。"
        assert trace.fast_escalation_requested and not trace.fast_escalation_validated
        assert trace.fast_escalation_count==0 and trace.fast_escalation_rejected_reason
    assert all(not schemas for schemas in p.tool_schemas)
    assert all("escalate" not in (m.content or "") for m in a.conversation.messages)


async def test_fast_escalation_valid_for_explicit_current_action():
    a,p=agent([ModelResponse(content=escalation("台账补一下"))])
    with action_trace_scope() as trace:
        result=await FastChatRuntime(a).run_fast_chat("那就把台账补一下吧")
        assert result.escalated and result.trigger_span=="台账补一下"
        assert trace.fast_escalation_count==1 and trace.fast_escalation_validated
    assert not a.conversation.messages


@pytest.mark.parametrize("text",["别把台账补一下",'只是引用“台账补一下”这句话',"小金毛"])
async def test_fast_escalation_requires_current_turn_evidence(text):
    a,p=agent([ModelResponse(content=escalation("台账补一下")),ModelResponse(content="收到。")])
    assert not (await FastChatRuntime(a).run_fast_chat(text)).escalated


async def test_rejected_fast_retry_cannot_execute_native_tool_calls_or_leak_draft():
    a,p=agent([ModelResponse(content="[escalate:tool]"),call()])
    result=await FastChatRuntime(a).run_fast_chat("小金毛")
    assert not result.escalated and result.content=="我在，继续聊吧。"
    assert a.registry.get("probe").calls==[]


async def test_same_tool_same_failure_only_repairs_once_and_locks_tool():
    tool=Probe([ToolResult(success=False,content="参数不对",error="invalid_query")])
    a,p=agent([call(query="bad"),call(query="still bad"),ModelResponse(content="没能完成，已停止重试。")],tool)
    with action_trace_scope() as trace:
        result=await a.run("请查询")
        assert len(tool.calls)==2 and result.content=="没能完成，已停止重试。"
        assert trace.repair_round==1 and trace.tool_retry_count==1 and trace.tool_locked==["probe"]
        assert trace.forced_finalization_reason=="tool_failure_limit"
        assert p.tool_schemas[-1] is None


async def test_repair_success_resolves_prior_error_without_replaying_success():
    tool=Probe([ToolResult(success=False,content="错",error="invalid_query"),ToolResult(success=True,content="新事实")])
    a,p=agent([call(query="bad"),call(query="fixed"),ModelResponse(content="已核实。")],tool)
    result=await a.run("查询")
    assert len(tool.calls)==2 and result.content=="已核实。"


async def test_same_tool_different_errors_still_have_per_tool_limit():
    tool=Probe([ToolResult(success=False,content="错一",error="error_one"),ToolResult(success=False,content="错二",error="error_two")])
    a,p=agent([call(),call(query="different"),call(query="third")],tool)
    result=await a.run("查询")
    assert len(tool.calls)==2 and "未完成" in result.content and result.result_status=="failed"


async def test_duplicate_memory_search_reused_or_blocked():
    tool=Probe([ToolResult(success=True,content="找到项链",data={"value":"蓝色"})]);tool.name="search_memories"
    a,p=agent([call(tool.name,"蓝色的项链"),call(tool.name,"蓝色项链"),ModelResponse(content="项链是蓝色。")],tool)
    await a.run("查项链记忆")
    assert tool.calls==["蓝色的项链"]
    results=[json.loads(m.content) for m in a.conversation.messages if m.role.value=="tool"]
    assert results[0]["data"]==results[1]["data"]


async def test_request_tool_group_blocked_after_known_tool_failure():
    tool=Probe([ToolResult(success=False,content="参数错",error="invalid_query")])
    group=ModelResponse(tool_calls=[ToolCall(id="group",name="request_tool_group",arguments={"group":"time"})])
    a,p=agent([call(),group,ModelResponse(content="参数无效，已停止。")],tool)
    with action_trace_scope() as trace:
        await a.run("查询")
        assert not any(e.event_type=="control_call_started" for e in trace.events)
        assert trace.forced_finalization_reason=="no_progress"


async def test_budget_warning_blocks_discovery_and_recall():
    a,p=agent([ModelResponse(tool_calls=[ToolCall(id="group",name="request_tool_group",arguments={"group":"time"})]),ModelResponse(content="本轮先收尾。")])
    with provider_budget_scope(10,policy=BudgetPolicy(1000,300,0,1300,200)) as budget,action_trace_scope() as trace:
        record_provider_tokens(700)
        assert budget.state is BudgetState.WARNING
        await a.run("查询")
        assert not any(e.event_type=="control_call_started" for e in trace.events)
        assert all(schema["function"]["name"] not in {"request_tool_group","inspect_tool_catalog","search_memories"} for schema in (p.tool_schemas[0] or []))


async def test_budget_danger_forces_finalization_even_if_model_calls_tool():
    a,p=agent([call()]);tool=a.registry.get("probe")
    with provider_budget_scope(10,policy=BudgetPolicy(1000,300,0,1300,200)),action_trace_scope() as trace:
        record_provider_tokens(850)
        result=await a.run("查询")
        assert p.tool_schemas==[None] and not tool.calls
        assert trace.budget_state=="DANGER" and trace.deterministic_fallback_used
        assert "尚未完成任何工具操作" in result.content


async def test_budget_exhausted_uses_deterministic_fallback_without_model():
    a,p=agent([call()])
    with provider_budget_scope(10,policy=BudgetPolicy(1000,300,0,1300,200)),action_trace_scope() as trace:
        record_provider_tokens(1000)
        result=await a.run("查询")
        assert not p.calls and result.result_status=="budget_exhausted"
        assert "预算已耗尽" in result.content and trace.deterministic_fallback_used


async def test_partial_success_is_preserved_and_danger_blocks_sibling_calls():
    tool=Probe([ToolResult(success=True,content="新事实"),ToolResult(success=False,content="错",error="invalid_query")])
    a,p=agent([call(query="ok"),call(query="bad"),call(query="repeat")],tool)
    result=await a.run("查询")
    assert len(tool.calls)==2 and result.result_status=="partial_success"
    assert "已完成" in result.content and "未完成" in result.content


async def test_no_progress_forces_stop_after_repeated_discovery():
    response=ModelResponse(tool_calls=[ToolCall(id="group",name="request_tool_group",arguments={"group":"missing"})])
    a,p=agent([response,response,ModelResponse(content="没有新能力，停止。")])
    with action_trace_scope() as trace:
        await a.run("查询")
        assert trace.forced_finalization_reason=="no_progress" and p.tool_schemas[-1] is None


def test_failure_fingerprint_ignores_values_and_dynamic_numbers():
    x=ToolResult(success=False,content="错",error="invalid value 1234")
    y=x.model_copy(update={"error":"invalid value 9876"})
    assert failure_fingerprint("probe",{"query":"a"},x)==failure_fingerprint("probe",{"query":"b"},y)


def test_memory_cache_does_not_mix_filters():
    s=LoopSafety();c=ToolCall(id="x",name="search_memories",arguments={"query":"项链","limit":1})
    s.observe(c,ToolResult(success=True,content="一条"))
    assert s.cached_search(c)
    assert s.cached_search(c.model_copy(update={"arguments":{"query":"项链","limit":9}})) is None


async def test_warning_rejects_unrelated_new_business_tool():
    a,p=agent([call(),ModelResponse(content="预算接近上限，不启动新支线。")])
    with provider_budget_scope(10,policy=BudgetPolicy(1000,300,0,1300,200)):
        record_provider_tokens(700)
        await a.run("闲聊")
    assert not a.registry.get("probe").calls


async def test_warning_allows_explicit_required_primary_tool():
    a,p=agent([call(),ModelResponse(content="主任务已查询。")])
    with provider_budget_scope(10,policy=BudgetPolicy(1000,300,0,1300,200)):
        record_provider_tokens(700)
        result=await a.run("查询",require_tool_call=True,required_tool="probe")
    assert a.registry.get("probe").calls==["q"] and result.content=="主任务已查询。"


async def test_validated_fast_upgrade_inherits_standard_limits_without_trace():
    a,p=agent([call(),call(query="second"),ModelResponse(content="两项查询完成")])
    result=await a.run("查询",fast_escalated=True)
    assert len(p.calls)==3 and a.registry.get("probe").calls==["q", "second"]
    assert p.tool_schemas[-1] is None and result.result_status=="completed"


async def test_normal_bounded_final_reply_can_report_completed_task():
    a,p=agent([call(),ModelResponse(content="主任务已完成。")])
    with action_trace_scope() as trace:
        result=await a.run("查询",fast_escalated=True)
        assert result.result_status=="completed" and not trace.partial_success


async def test_budget_becomes_danger_between_sibling_calls_stops_remaining_tool():
    class Spending(Probe):
        async def execute(self,args):
            result=await super().execute(args)
            record_provider_tokens(850)
            return result
    tool=Spending([ToolResult(success=True,content="已取得第一条事实")])
    two=ModelResponse(tool_calls=[ToolCall(id="a",name="probe",arguments={"query":"a"}),ToolCall(id="b",name="probe",arguments={"query":"b"})])
    a,p=agent([two,ModelResponse(content="仅第一项完成，第二项因预算停止。")],tool)
    with provider_budget_scope(10,policy=BudgetPolicy(1000,300,0,1300,200)):
        result=await a.run("查询两项",required_tool="probe")
        assert result.result_status=="partial_success"
    assert tool.calls==["a"] and p.tool_schemas[-1] is None


@pytest.mark.parametrize("reason",["failure", "warning", "danger"])
async def test_frozen_permission_tail_cannot_bypass_runtime_guards(reason):
    from zhaoxi.core.agent import PendingAgentInvocation
    from zhaoxi.tools.discovery import ToolDiscoveryState
    a,p=agent([])
    discovery=ToolDiscoveryState(a._tool_context("查询"))
    safety=a._safety_state(discovery)
    if reason=="failure":
        safety.observe(ToolCall(id="failed",name="probe",arguments={"query":"bad"}),
            ToolResult(success=False,content="参数无效",error="tool_validation_error"))
    calls=[ToolCall(id="catalog",name="inspect_tool_catalog",arguments={"action":"summary"})]
    if reason=="danger":
        calls.append(ToolCall(id="read",name="probe",arguments={"query":"new"}))
    pending=PendingAgentInvocation(request_id="resume",name="probe",arguments={},invocation_id="resume",
        tool_call_id="first",user_intent="查询",remaining_calls=calls,discovery=discovery)
    with provider_budget_scope(10,policy=BudgetPolicy(1000,300,0,1300,200)):
        if reason!="failure":record_provider_tokens(850 if reason=="danger" else 700)
        await a._execute_remaining_calls(pending)
    assert not discovery.cache
    assert "runtime_call_blocked" in discovery.observations[0]
    if reason=="danger":
        assert a.registry.get("probe").calls==[]
        assert safety.outcomes[-1][1].metadata["not_executed"]
        assert "未执行" in safety.fallback()


def test_structured_escalation_requires_reason_field():
    draft='[escalate:{"kind":"tool","trigger_span":"补一下"}]'
    assert FastChatRuntime.validated_request(draft,"把台账补一下")[2]=="missing_reason"


async def test_unknown_tool_in_permission_tail_preserves_prior_success():
    from zhaoxi.core.agent import PendingAgentInvocation
    from zhaoxi.tools.discovery import ToolDiscoveryState
    a,p=agent([])
    discovery=ToolDiscoveryState(a._tool_context("查询"))
    safety=a._safety_state(discovery)
    safety.observe(ToolCall(id="ok",name="probe",arguments={"query":"ok"}),ToolResult(success=True,content="已完成"))
    pending=PendingAgentInvocation(request_id="resume",name="probe",arguments={},invocation_id="resume",
        tool_call_id="first",user_intent="查询",remaining_calls=[ToolCall(id="missing",name="missing_tool")],discovery=discovery)
    await a._execute_remaining_calls(pending)
    assert len(safety.outcomes)==2 and safety.outcomes[-1][1].metadata["error_code"]=="tool_not_found"
    assert "已完成" in safety.fallback() and "未完成" in safety.fallback()


def test_unknown_write_outcome_is_locked_without_automatic_replay():
    safety=LoopSafety()
    result=ToolResult(success=False,content="连接中断",error="connection_lost",metadata={"unknown_outcome":True})
    safety.observe(ToolCall(id="write",name="ledger",arguments={"value":1}),result,mutation=True)
    assert "ledger" in safety.locked and safety.forced_reason=="tool_failure_limit"
    assert "结果未知" in safety.fallback() and "已完成：" not in safety.fallback()


async def test_actual_missing_tool_in_permission_tail_allows_capability_discovery():
    from zhaoxi.core.agent import PendingAgentInvocation
    from zhaoxi.tools.discovery import ToolDiscoveryState
    a,p=agent([])
    discovery=ToolDiscoveryState(a._tool_context("查询"))
    calls=[ToolCall(id="missing",name="missing_tool"),ToolCall(id="catalog",name="inspect_tool_catalog",arguments={"action":"summary"})]
    pending=PendingAgentInvocation(request_id="resume",name="probe",arguments={},invocation_id="resume",
        tool_call_id="first",user_intent="查询",remaining_calls=calls,discovery=discovery)
    await a._execute_remaining_calls(pending)
    assert discovery.cache and discovery.safety.progress


def test_safety_metrics_keep_failure_fingerprint_across_permission_resume():
    safety=LoopSafety()
    call=ToolCall(id="a",name="ledger",arguments={"value":1})
    result=ToolResult(success=False,content="参数错误",error="tool_validation_error")
    first=safety.observe(call,result)
    assert safety.metrics()["tool_failure_fingerprint"]==first["tool_failure_fingerprint"]
    safety.observe(call,result)
    assert safety.metrics()["tool_retry_count"]==1 and safety.metrics()["tool_locked"]==["ledger"]


def test_budget_metrics_follow_provider_usage_outside_standard_loop():
    with provider_budget_scope(10,policy=BudgetPolicy(1000,300,0,1300,200)),action_trace_scope() as trace:
        record_provider_tokens(700)
        assert trace.budget_state=="WARNING" and trace.budget_remaining_ratio==pytest.approx(.3)
        record_provider_tokens(150)
        assert trace.budget_state=="DANGER" and trace.budget_remaining_ratio==pytest.approx(.15)


@pytest.mark.parametrize("expanded,business_calls,tool_round,limit,credited", [
    (True, False, 0, 1, True),
    (False, False, 0, 1, False),
    (True, True, 0, 1, False),
    (True, False, 1, 1, False),
    (True, False, 0, 0, False),
])
def test_discovery_credit_requires_new_capability_without_business_execution(expanded, business_calls, tool_round, limit, credited):
    safety = LoopSafety(tool_round=tool_round, discovery_limit=limit)
    assert safety.credit_discovery_round(expanded=expanded, business_calls=business_calls) == credited
    assert safety.discovery_round == int(credited)


def test_productive_discovery_credit_is_bounded_and_actual_calls_still_counted():
    safety = LoopSafety()
    assert safety.credit_discovery_round(expanded=True, business_calls=False)
    assert not safety.credit_discovery_round(expanded=True, business_calls=False)
    for _ in range(3):
        safety.begin_round()
    assert not safety.model_limit_reached
    safety.begin_round()
    assert safety.model_limit_reached
    assert safety.metrics()["standard_model_round"] == 4
    assert safety.metrics()["discovery_round"] == 1


@pytest.mark.parametrize("enabled", [False, True])
async def test_debug_multi_model_calls_allows_control_rounds_before_business_tool(enabled):
    controls = [ModelResponse(tool_calls=[ToolCall(id=str(i), name="inspect_tool_catalog", arguments={"action": action})])
                for i, action in enumerate(["summary", "list_groups"])]
    a, provider = agent([*controls, call(), ModelResponse(content="已核验。")])
    a.max_steps = 5
    a.allow_multi_model_calls = enabled
    with action_trace_scope():
        response = await a.run("查询", fast_escalated=True)
    if enabled:
        assert a.registry.get("probe").calls == ["q"]
        assert len(provider.calls) == 4 and response.content == "已核验。"
    else:
        assert a.registry.get("probe").calls == []
        assert len(provider.calls) == 3 and provider.tool_schemas[-1] is None


def test_multi_model_debug_preserves_other_guards_and_existing_request_snapshot():
    from zhaoxi.tools.discovery import ToolDiscoveryState
    a, _ = agent([])
    a.max_steps = 5
    a.allow_multi_model_calls = True
    discovery = ToolDiscoveryState(a._tool_context("查询"))
    safety = a._safety_state(discovery, fast_escalated=True)
    assert safety.model_limit == 5
    assert (safety.tool_limit, safety.repair_limit, safety.discovery_limit) == (4, 1, 1)
    a.allow_multi_model_calls = False
    assert a._safety_state(discovery, fast_escalated=True) is safety
    assert a._safety_state(ToolDiscoveryState(a._tool_context("查询")), fast_escalated=True).model_limit == 3


@pytest.mark.parametrize("fast_escalated", [False, True])
async def test_multi_model_debug_executes_four_business_rounds_then_reserves_last_step(fast_escalated):
    tool = Probe([ToolResult(success=True, content=f"事实 {i}", data={"value": i}) for i in range(4)])
    a, provider = agent([*[call(query=str(i), id=f"call-{i}") for i in range(5)]], tool)
    a.max_steps = 5
    a.allow_multi_model_calls = True
    with action_trace_scope() as trace:
        await a.run("继续核验", fast_escalated=fast_escalated)
    assert tool.calls == ["0", "1", "2", "3"]
    assert len(provider.calls) == 5
    assert all(provider.tool_schemas[i] for i in range(4))
    assert provider.tool_schemas[4] is None
    assert trace.standard_tool_round == 4


@pytest.mark.parametrize("enabled", [False, True])
async def test_multi_model_debug_still_stops_on_repeated_tool_failures(enabled):
    tool = Probe([ToolResult(success=False, content="失败", error="unavailable")])
    a, provider = agent([call(query="first"), call(query="second"), ModelResponse(content="暂时无法核验。")], tool)
    a.allow_multi_model_calls = enabled
    with action_trace_scope() as trace:
        await a.run("核验")
    assert tool.calls == ["first", "second"]
    assert provider.tool_schemas[-1] is None
    assert trace.forced_finalization_reason == "tool_failure_limit"


@pytest.mark.parametrize("final_only", [False, True])
@pytest.mark.parametrize("fenced", [False, True])
async def test_bare_tool_arguments_never_become_reply_or_execute_again(final_only, fenced):
    payload = json.dumps({"operation": "record", "arguments": {
        "action": "create", "resource": "meal", "description": "fixture"}})
    raw = "```json\n" + payload + "\n```" if fenced else payload
    tool = Probe([ToolResult(success=True, content="已查询", data={"value": 1})])
    a, p = agent([call(), ModelResponse(content=raw), ModelResponse(content="只完成了查询，尚未录入。")], tool)
    a.decision_mode = "agency"
    if final_only:
        a.max_steps = 2
    with action_trace_scope() as trace:
        result = await a.run("查询后录入")
        assert any(e.event_type == "main_reply_protocol" and e.error_code == "invalid_reply_protocol"
                   for e in trace.events)
        if final_only:
            assert len(p.calls) == 2 and trace.response_status == "failed"
            assert "已完成" in result.content and "模型未能生成完整正文" in result.content
        else:
            assert len(p.calls) == 3 and p.tool_schemas[-1] is None
            assert trace.forced_finalization_reason == "reply_protocol_recovery"
            assert result.content == "只完成了查询，尚未录入。"
    assert tool.calls == ["q"]
    assert payload not in result.content
    assert all(payload not in (m.content or "") for m in a.conversation.messages)


@pytest.mark.parametrize("final_only", [False, True])
async def test_incomplete_stop_envelope_preserves_tools_and_never_saves_partial(final_only):
    partial = "比较到一半，接下来比"
    invalid = ModelResponse(content=json.dumps({"reply": partial}), finish_reason="stop",
                            raw_metadata={"main_reply_contract": True})
    tool = Probe([ToolResult(success=True, content="已查询", data={"value": 1})])
    a, p = agent([call(), invalid, ModelResponse(content="查询结果已确认。")], tool)
    a.decision_mode = "agency"
    if final_only:
        a.max_steps = 2
    with action_trace_scope() as trace:
        result = await a.run("核验结果")
    assert tool.calls == ["q"]
    assert partial not in result.content
    assert all(partial not in (m.content or "") for m in a.conversation.messages)
    if final_only:
        assert len(p.calls) == 2 and trace.response_status == "failed"
        assert "模型未能生成完整正文" in result.content
    else:
        assert len(p.calls) == 3 and p.tool_schemas[-1] is None
        assert result.content == "查询结果已确认。"
