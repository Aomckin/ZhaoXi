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
    provider = FakeProvider([ModelResponse(tool_calls=[ToolCall(id="focus-1", name="lifehud", arguments={
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
    assert any(m.role.value == "tool" and "fixture-focus-1" in m.content for m in provider.calls[-1])
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


async def test_model_budget_exhausted_does_not_add_recovery_call():
    agent, provider, gateway, seen = setup([ModelResponse(content=" " * 81)], model_limit=2)
    response = await gateway.chat(UnifiedMessage(channel="web", content="开个25分钟番茄钟", request_id="bounded"))
    assert "已完成：lifehud" in response.content
    assert len(provider.calls) == 2 and len(seen) == 2
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
