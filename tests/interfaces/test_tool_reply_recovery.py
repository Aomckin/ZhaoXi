"""Real LifeHUD adapter with local HTTP fixtures: one write, then reply only."""
import json

import httpx
import pytest
from conftest import FakeProvider

from tools.lifehud_tool.client import LifeHudClient
from tools.lifehud_tool.tool import LifeHudTool
from zhaoxi.config.settings import Settings
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.message import is_user_visible_message
from zhaoxi.interfaces import InterfaceGateway, UnifiedMessage
from zhaoxi.models.types import ModelResponse, ToolCall
from zhaoxi.tools.registry import ToolRegistry


def final(text="25 分钟番茄钟已经开启，先把这段代码写完。"):
    return ModelResponse(content=json.dumps({"reply": text, "awareness": {"mode": "NONE"}}, ensure_ascii=False))


def setup(responses, *, model_limit=3, server_status=200):
    seen = []
    def handler(request):
        seen.append((request.method, request.url.path))
        if request.method == "POST":
            assert json.loads(request.content)["plannedMinutes"] == 25
            return httpx.Response(server_status, json={"id": "fixture-focus-1", "plannedMinutes": 25})
        return httpx.Response(200, json={"id": "fixture-focus-1", "plannedMinutes": 25, "status": "ACTIVE"})
    tool = LifeHudTool(LifeHudClient("http://lifehud.test", transport=httpx.MockTransport(handler),
                                   retry_backoff_seconds=0))
    registry = ToolRegistry()
    registry.register(tool)
    registry.update_tools(name="lifehud", confirm_write=False)
    class ContractProvider(FakeProvider):
        async def generate(self, messages, tools=None, **kwargs):
            response = await super().generate(messages, tools, **kwargs)
            if kwargs.get("response_format", {}).get("json_schema", {}).get("name") == "reply_repair":
                try:
                    value = json.loads(response.content or "")
                except ValueError:
                    return response
                if isinstance(value, dict) and value.get("awareness") == {"mode": "NONE"} and value.get("reply"):
                    return response.model_copy(update={"content": json.dumps({"reply": value["reply"]}, ensure_ascii=False)})
            return response
    provider = ContractProvider([ModelResponse(tool_calls=[ToolCall(id="focus-1", name="lifehud", arguments={
        "operation": "focus", "arguments": {"action": "start", "plannedMinutes": 25,
                                             "title": "代码开发"}})]), *responses])
    agent = ZhaoxiAgent(provider=provider, registry=registry, context_builder=ContextBuilder("朝汐"),
                        decision_mode="agency")
    agent.settings = Settings(_env_file=None, standard_model_round_limit=model_limit, standard_tool_round_limit=2,
                              standard_repair_round_limit=1)
    gateway = InterfaceGateway(agent)
    # Keep the test strictly about foreground delivery and retries.
    gateway._enqueue_maintenance = lambda *a, **kw: None
    return agent, provider, gateway, seen


@pytest.mark.parametrize("raw", [" " * 81,
    '{"reply":"","awareness":{"mode":"NONE"}}',
    '<decision-awareness>{"mode":"ADVISE"}</decision-awareness>',
    '[emoji:missing]', '{"reply":"截断'])
async def test_tool_success_then_missing_reply_uses_one_tool_free_recovery(raw):
    agent, provider, gateway, seen = setup([ModelResponse(content=raw), final()])
    response = await gateway.chat(UnifiedMessage(channel="web", content="在 LifeHUD 开个25分钟番茄钟", request_id="start-focus"))
    assert response.content.startswith("25 分钟番茄钟已经开启")
    assert seen == [("POST", "/api/focus/start"), ("GET", "/api/focus/current")]
    assert len(provider.calls) == 3 and provider.tool_schemas[-1] is None
    assert "tool_choice" not in provider.options[-1]
    assert agent.last_action_trace["response_status"] == "succeeded"
    assert agent.last_action_trace["runtime_metrics"]["tool_call_count"] == 1
    assert any("fixture-focus-1" in (m.content or "") for m in provider.calls[-1])
    assert provider.options[-1]["response_format"]["json_schema"]["name"] == "reply_repair"
    assert sum(m.role.value == "user" for m in agent.conversation.messages) == 1
    assert len([m for m in agent.conversation.messages if m.role.value == "assistant" and is_user_visible_message(m)]) == 1


async def test_repeated_blank_final_returns_receipt_and_manual_retry_only_generates_reply():
    agent, provider, gateway, seen = setup([ModelResponse(content=" " * 81), ModelResponse(content="")])
    response = await gateway.chat(UnifiedMessage(channel="web", content="开个25分钟番茄钟", request_id="receipt"))
    assert "已完成：lifehud" in response.content and "重新生成只补回复" in response.content
    assert agent.last_action_trace["response_status"] == "failed"
    assert agent.conversation.messages[-1].visibility == "notice" and agent.conversation.messages[-1].tool_turn
    assert len(provider.calls) == 3
    before = list(seen)
    provider.responses.clear()
    provider.responses.append(final())
    retry = await gateway.regenerate(response.message_id, request_id="retry-receipt")
    assert retry.content.startswith("25 分钟番茄钟已经开启")
    assert len(provider.calls) == 4 and provider.tool_schemas[-1] is None and seen == before
    assert agent.last_action_trace["response_status"] == "succeeded"
    assert sum(m.role.value == "user" for m in agent.conversation.messages) == 1


async def test_unanswered_user_with_internal_tool_messages_can_resume_without_replay():
    agent, provider, gateway, seen = setup([final()])
    user = agent.conversation.add_user("开个25分钟番茄钟")
    agent.conversation.add_assistant(None, tool_calls=[ToolCall(id="done", name="lifehud", arguments={})])
    agent.conversation.add_tool('{"success":true,"content":"已开启25分钟番茄钟","data":{"id":"existing"}}',
                                tool_call_id="done", name="lifehud")
    provider.responses.clear()
    provider.responses.append(final())
    retry = await gateway.regenerate(user.message_id, request_id="retry-user-after-tool")
    assert retry.content.startswith("25 分钟番茄钟已经开启")
    assert seen == [] and len(provider.calls) == 1 and provider.tool_schemas[-1] is None
    assert sum(m.role.value == "user" for m in agent.conversation.messages) == 1


async def test_ordinary_model_limit_reserves_one_tool_free_reply_repair():
    agent, provider, gateway, seen = setup([ModelResponse(content=" " * 81)], model_limit=2)
    response = await gateway.chat(UnifiedMessage(channel="web", content="开个25分钟番茄钟", request_id="bounded"))
    assert "已完成：lifehud" in response.content
    assert len(provider.calls) == 3 and provider.tool_schemas[-1] is None and len(seen) == 2
    assert agent.last_action_trace["runtime_metrics"]["repair_round"] == 1
    assert agent.last_action_trace["response_status"] == "failed"


async def test_failed_lifehud_action_never_becomes_a_success_receipt():
    agent, provider, gateway, seen = setup([ModelResponse(content=" " * 81), ModelResponse(content="")], server_status=400)
    response = await gateway.chat(UnifiedMessage(channel="web", content="开个25分钟番茄钟", request_id="failed-focus"))
    assert "仍失败：lifehud" in response.content and "已完成：无" in response.content
    assert agent.last_action_trace["response_status"] == "failed"
    assert seen == [("POST", "/api/focus/start")]


async def test_later_visible_reply_or_new_user_still_blocks_old_user_retry():
    agent, provider, gateway, seen = setup([final()])
    user = agent.conversation.add_user("开个25分钟番茄钟")
    agent.conversation.add_assistant(None, tool_calls=[ToolCall(id="done", name="lifehud", arguments={})])
    agent.conversation.add_tool('{"success":true}', tool_call_id="done", name="lifehud")
    agent.conversation.add_assistant("已经开了。")
    with pytest.raises(ValueError, match="最后一条未回复"):
        await gateway.regenerate(user.message_id, request_id="old")
    assert len(provider.calls) == 0 and seen == []


async def test_saved_failure_notice_after_restart_keeps_retry_tool_free(tmp_path):
    from zhaoxi.session.sqlite import SQLiteSessionStore
    from zhaoxi.session.base import Session
    agent, provider, gateway, seen = setup([ModelResponse(content=" " * 81), ModelResponse(content="")])
    response = await gateway.chat(UnifiedMessage(channel="web", content="开个25分钟番茄钟", request_id="before-restart"))
    store = SQLiteSessionStore(tmp_path / "session.db")
    await store.save(Session(id="local", conversation=agent.conversation))
    restored = await store.get("local")
    assert all(m.role.value != "tool" and not m.tool_calls for m in restored.conversation.messages)
    assert restored.conversation.messages[-1].visibility == "notice"
    restarted, new_provider, new_gateway, new_requests = setup([])
    restarted.conversation = restored.conversation
    new_provider.responses.clear()
    new_provider.responses.append(final())
    reply = await new_gateway.regenerate(response.message_id, request_id="after-restart")
    assert reply.content.startswith("25 分钟番茄钟已经开启")
    assert new_provider.tool_schemas == [None] and new_requests == []
    assert seen == [("POST", "/api/focus/start"), ("GET", "/api/focus/current")]


@pytest.mark.parametrize("failure", ["provider_tool_arguments_invalid", "provider_response_invalid"])
async def test_provider_protocol_failure_repairs_only_reply(failure):
    from zhaoxi.errors import ProviderError
    agent, provider, gateway, seen = setup([ModelResponse(content="bad"), final()], model_limit=2)
    generate = provider.generate
    async def failing(messages, tools=None, **kwargs):
        response = await generate(messages, tools, **kwargs)
        if len(provider.calls) == 2:
            raise ProviderError("malformed protocol", code=failure, retryable=False)
        return response
    provider.generate = failing
    response = await gateway.chat(UnifiedMessage(channel="web", content="开个25分钟番茄钟", request_id=failure))
    assert response.content.startswith("25 分钟")
    assert len(provider.calls) == 3 and provider.tool_schemas[-1] is None
    assert len(seen) == 2
    assert agent.last_action_trace["response_status"] == "succeeded"
    assert agent.last_action_trace["runtime_metrics"]["repair_round"] == 1
    if failure == "provider_tool_arguments_invalid":
        assert response.activity["result_status"] == "partial_success"


@pytest.mark.parametrize("exhaustion", ["tokens", "calls"])
async def test_reply_repair_never_exceeds_provider_budget(exhaustion):
    from zhaoxi.reliability.retry import current_budget
    agent, provider, gateway, seen = setup([ModelResponse(content="")])
    generate = provider.generate
    async def exhausted(messages, tools=None, **kwargs):
        response = await generate(messages, tools, **kwargs)
        if len(provider.calls) == 2:
            budget = current_budget()
            if exhaustion == "tokens":
                budget.total_tokens = budget.max_total_tokens
            else:
                budget.calls = budget.max_calls
        return response
    provider.generate = exhausted
    events = []
    gateway.event_sink = events.append
    response = await gateway.chat(UnifiedMessage(channel="web", content="开个番茄钟", request_id=exhaustion))
    assert len(provider.calls) == 2 and len(seen) == 2
    assert response.activity["result_status"] == "failed"
    assert response.activity["task_status"] == "completed"
    finished = [e["event"] for e in events if e.get("event", {}).get("event_type") == "runtime_finished"]
    assert finished[-1]["outcome"] == "failed"


async def test_danger_budget_repairs_with_compact_receipts_without_extension():
    from zhaoxi.reliability.retry import current_budget
    agent, provider, gateway, seen = setup([ModelResponse(content='{"reply":"有正文但缺摘要"}', raw_metadata={"main_reply_contract": True}), final()], model_limit=2)
    generate = provider.generate
    budgets = []
    async def danger(messages, tools=None, **kwargs):
        response = await generate(messages, tools, **kwargs)
        budget = current_budget()
        if len(provider.calls) == 2:
            budget.total_tokens = int(budget.max_total_tokens * .92)
        budgets.append(budget.max_total_tokens)
        return response
    provider.generate = danger
    response = await gateway.chat(UnifiedMessage(channel="web", content="开个番茄钟", request_id="danger-repair"))
    assert response.content.startswith("25 分钟")
    assert len(provider.calls) == 3 and len(seen) == 2
    assert provider.tool_schemas[-1] is None and len(set(budgets)) == 1
    assert "fixture-focus-1" in provider.calls[-1][-1].content
    assert sum(len(m.content or "") for m in provider.calls[-1]) < 16000


async def test_slow_finalization_does_not_emit_canned_runtime_notice():
    import asyncio
    agent, provider, gateway, seen = setup([final()])
    agent.settings = Settings(_env_file=None, interim_reply_threshold_seconds=.01)
    generate = provider.generate
    async def slow(messages, tools=None, **kwargs):
        if provider.calls:
            await asyncio.sleep(.04)
        return await generate(messages, tools, **kwargs)
    provider.generate = slow
    events = []
    gateway.event_sink = events.append
    await gateway.chat(UnifiedMessage(channel="web", content="开个番茄钟", request_id="progress"))
    interim = [e for e in events if e["type"] == "interim_reply"]
    assert interim == []
    assert len(provider.calls) == 2 and len(seen) == 2
    assert all(m.visibility != "interim" for m in agent.conversation.messages)


async def test_runtime_progress_cancellation_stops_pending_model_call():
    import asyncio
    from zhaoxi.errors import AgentLoopError
    agent, provider, gateway, seen = setup([final()])
    agent.timeout_seconds = .04
    agent.settings = Settings(_env_file=None, interim_reply_threshold_seconds=.01)
    generate = provider.generate
    stopped = asyncio.Event()
    async def waiting(messages, tools=None, **kwargs):
        if provider.calls:
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        return await generate(messages, tools, **kwargs)
    provider.generate = waiting
    gateway.event_sink = lambda event: None
    response = await gateway.chat(UnifiedMessage(channel="web", content="开个番茄钟", request_id="cancel"))
    assert response.activity["response_status"] == "failed"
    assert stopped.is_set() and len(seen) == 2


async def test_repeated_provider_protocol_failure_has_one_repair_and_failed_terminal():
    from zhaoxi.errors import ProviderError
    agent, provider, gateway, seen = setup([final()], model_limit=2)
    generate = provider.generate
    async def failing(messages, tools=None, **kwargs):
        response = await generate(messages, tools, **kwargs)
        if len(provider.calls) >= 2:
            raise ProviderError("malformed", code="provider_tool_arguments_invalid", retryable=False)
        return response
    provider.generate = failing
    events = []
    gateway.event_sink = events.append
    response = await gateway.chat(UnifiedMessage(channel="web", content="开个番茄钟", request_id="repeated"))
    assert len(provider.calls) == 3 and len(seen) == 2
    assert response.activity["result_status"] == "failed"
    assert response.activity["response_status"] == "failed"
    terminal = [e["event"] for e in events if e.get("event", {}).get("event_type") == "runtime_finished"]
    assert terminal[-1]["outcome"] == "failed"


async def test_disabled_reply_repair_never_adds_call():
    agent, provider, gateway, seen = setup([ModelResponse(content="")], model_limit=2)
    agent.settings.standard_repair_round_limit = 0
    response = await gateway.chat(UnifiedMessage(channel="web", content="开个番茄钟", request_id="disabled-repair"))
    assert len(provider.calls) == 2 and len(seen) == 2
    assert response.activity["result_status"] == "failed"


@pytest.mark.parametrize("enabled", [False, True])
async def test_fast_finalization_or_disabled_interim_emits_no_runtime_notice(enabled):
    agent, provider, gateway, seen = setup([final()])
    agent.settings = Settings(_env_file=None, interim_reply_enabled=enabled,
                              interim_reply_threshold_seconds=1000)
    events = []
    gateway.event_sink = events.append
    await gateway.chat(UnifiedMessage(channel="web", content="开个番茄钟", request_id="quick"))
    assert not any(e["type"] == "interim_reply" for e in events)
    assert len(seen) == 2


async def test_reply_repair_does_not_upgrade_failed_action_to_partial_success():
    from zhaoxi.errors import ProviderError
    agent, provider, gateway, seen = setup([final("工具没有完成，请检查服务。")], server_status=400)
    generate = provider.generate
    async def failing(messages, tools=None, **kwargs):
        response = await generate(messages, tools, **kwargs)
        if len(provider.calls) == 2:
            raise ProviderError("malformed", code="provider_tool_arguments_invalid", retryable=False)
        return response
    provider.generate = failing
    response = await gateway.chat(UnifiedMessage(channel="web", content="开个番茄钟", request_id="failed-action-repair"))
    assert len(provider.calls) == 3 and len(seen) == 1
    assert response.activity["task_status"] == "failed"
    assert response.activity["result_status"] == "failed"
    assert response.activity["response_status"] == "succeeded"


@pytest.mark.parametrize("enabled,threshold,sent", [(True, 0, True), (False, 0, False), (True, 1000, False)])
async def test_same_action_call_carries_personal_interim_without_extra_round(enabled, threshold, sent):
    text = "唔，暗苟，刚才那条留好了，我再核对一下时间呀。"
    follow = ModelResponse(content=text,
        tool_calls=[ToolCall(id="verify", name="lifehud", arguments={"operation":"focus.current", "arguments":{}})])
    agent, provider, gateway, seen = setup([follow, final()])
    agent.context_builder.personality_prompt = "你是朝汐，对暗苟亲近自然。"
    agent.settings = Settings(_env_file=None, interim_reply_enabled=enabled, interim_reply_threshold_seconds=threshold)
    events = []
    gateway.event_sink = events.append
    result = await gateway.chat(UnifiedMessage(channel="web", content="开番茄钟并核对", request_id="inline"))
    interim = [e for e in events if e["type"] == "interim_reply"]
    assert len(interim) == int(sent)
    if sent:
        assert interim[0]["content"] == text and not interim[0]["terminates_turn"]
    assert len(provider.calls) == 3 and len(seen) == 3
    assert result.content.startswith("25 分钟")
    assert "你是朝汐，对暗苟亲近自然" in provider.calls[1][0].content
    assert "同一次 response.content" in provider.calls[1][0].content if enabled else True
    assert all("emit_interim_reply" != s["function"]["name"] for schemas in provider.tool_schemas for s in schemas or [])
    assert all(text not in (m.content or "") for m in agent.conversation.messages)


async def test_reply_only_repair_retains_character_image_and_confirmed_results():
    bad = ModelResponse(content=json.dumps({"reply":""}), raw_metadata={"main_reply_contract":True})
    agent, provider, gateway, seen = setup([bad, final()])
    agent.context_builder.personality_prompt = "fixture-personality"
    agent.context_builder.expression_prompt = "fixture-expression"
    import base64
    from io import BytesIO
    from PIL import Image
    output = BytesIO()
    Image.new("RGB", (2, 2)).save(output, format="PNG")
    image = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()
    result = await gateway.chat(UnifiedMessage(channel="web", content="记录截图中的日程", images=[image], request_id="repair-image"))
    assert result.activity["response_status"] == "succeeded" and len(provider.calls) == 3
    assert "fixture-personality" in provider.calls[-1][0].content
    assert "fixture-expression" in provider.calls[-1][0].content
    assert provider.calls[-1][-1].images == [image]
    assert provider.options[-1]["response_format"]["json_schema"]["name"] == "reply_repair"
    schema = provider.options[-1]["response_format"]["json_schema"]["schema"]
    assert schema["required"] == ["reply"] and "awareness" not in schema["properties"]
    assert len(seen) == 2


@pytest.mark.parametrize("broken_delivery", [False, True])
async def test_first_action_native_speech_precedes_execution_and_is_not_replayed(broken_delivery):
    agent, provider, gateway, seen = setup([final()])
    text = "唔，暗苟，我先给你把番茄钟开起来呀。"
    provider.responses[0].content = text
    agent.settings.interim_reply_threshold_seconds = 0
    events = []
    def sink(event):
        if event["type"] == "interim_reply":
            assert seen == []  # The next write has not started yet.
            if broken_delivery:
                raise RuntimeError("SSE unavailable")
        events.append(event)
    gateway.event_sink = sink
    result = await gateway.chat(UnifiedMessage(channel="web", content="开个番茄钟", request_id="first-native"))
    assert result.content.startswith("25 分钟")
    assert len(provider.calls) == 2 and len(seen) == 2
    assert "response_format" not in provider.options[0]
    assert all(text not in (m.content or "") for m in agent.conversation.messages)
    assert all(text not in (m.content or "") for m in provider.calls[1])
    assert len([e for e in events if e["type"] == "interim_reply"]) == int(not broken_delivery)


async def test_legacy_interim_schema_requires_explicit_debug_flag():
    agent, provider, gateway, _ = setup([final()])
    agent.settings.interim_legacy_tool_enabled = True
    await gateway.chat(UnifiedMessage(channel="web", content="开个番茄钟", request_id="debug-interim"))
    assert any(s["function"]["name"] == "emit_interim_reply" for s in provider.tool_schemas[0])
