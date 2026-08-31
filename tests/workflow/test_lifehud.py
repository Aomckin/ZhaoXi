import asyncio
import json
from pathlib import Path

import httpx
import pytest

from conftest import FakeProvider
from zhaoxi.cognitive.coordinator import CognitiveCoordinator
from zhaoxi.cognitive.router import CognitiveRoute, CognitiveRouter
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.models.types import ModelResponse, ToolCall
from zhaoxi.permission.executor import ToolExecutor
from zhaoxi.tools.integrations.lifehud import (
    LifeHudClient,
    LifeHudError,
    create_lifehud_context_tools,
    create_lifehud_focus_tools,
)
from zhaoxi.tools.registry import ToolRegistry
from zhaoxi.workflow.loader import WorkflowLoader
from zhaoxi.workflow.models import WorkflowStatus
from zhaoxi.workflow.registry import WorkflowRegistry
from zhaoxi.workflow.runtime import WorkflowRuntime


def session(status="RUNNING", mode="IRON_CURTAIN", session_id="focus-1"):
    return {
        "id": session_id,
        "mode": mode,
        "status": status,
        "title": "开发 v0.5.1",
        "taskId": None,
        "startedAt": "2026-08-31T02:00:00Z",
        "endedAt": None if status in {"RUNNING", "PAUSED"} else "2026-08-31T03:00:00Z",
        "plannedMinutes": None,
        "actualSeconds": 60,
        "actualMinutes": 1,
        "effectiveSeconds": 60,
        "effectiveMinutes": 1,
        "note": "",
        "updatedAt": "2026-08-31T02:01:00Z",
        "relatedTaskIds": [],
        "segments": [],
        "breakMinutes": 5,
    }


def focus_context(active=None, **extra):
    return {
        "schemaVersion": "1",
        "generatedAt": "2026-08-31T02:30:00Z",
        "date": "2026-08-31",
        "focus": {
            "effectiveMinutes": 45,
            "sessionCount": 2,
            "active": active,
            "recent": [],
            "daily": [{"date": "2026-08-31", "effectiveMinutes": 45}],
        },
        **extra,
    }


def today_context(**extra):
    return {
        "schemaVersion": "1",
        "generatedAt": "2026-08-31T02:30:00Z",
        "date": "2026-08-31",
        "status": {"energy": 122, "level": 17, "exp": 526, "title": "铁幕行者", "checkIn": None, "activeFocus": None},
        "focus": focus_context()["focus"],
        "tasks": {"completed": 2, "remaining": 3, "items": []},
        "sleep": None,
        "meal": None,
        "dreams": {"active": [], "goals": [], "milestones": []},
        "rituals": {"completedToday": [], "available": []},
        "media": {"watchingAnime": [], "playingGames": [], "animeSessions": [], "gameSessions": [], "items": [], "recentlyCompleted": []},
        "timeline": [],
        **extra,
    }


def runtime_for(handler):
    transport = httpx.MockTransport(handler)
    client = LifeHudClient(
        "http://lifehud.test", transport=transport, retry_backoff_seconds=0
    )
    tools = ToolRegistry()
    for tool in [*create_lifehud_context_tools(client), *create_lifehud_focus_tools(client)]:
        tools.register(tool)
    workflows = WorkflowRegistry(tools)
    root = Path(__file__).parents[2] / "workflows" / "lifehud"
    for definition in WorkflowLoader().load_directory(root):
        workflows.register(definition)
    return WorkflowRuntime(workflows, ToolExecutor(tools))


async def test_today_parses_null_empty_and_ignores_unknown_fields():
    client = LifeHudClient(
        "http://lifehud.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=today_context(futureField={"ok": True}))),
    )
    value = await client.today()
    assert value.schemaVersion == "1"
    assert value.sleep is None and value.timeline == []
    assert value.generatedAt.tzinfo is not None
    assert "futureField" not in value.model_fields_set


async def test_lifehud_tool_converts_utc_for_display_without_mutating_source():
    payload = focus_context(session(status="COMPLETED"))
    client = LifeHudClient(
        "http://lifehud.test",
        display_timezone="Asia/Shanghai",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
    )

    source = await client.focus()
    tool = next(tool for tool in create_lifehud_context_tools(client) if tool.name == "lifehud_focus")
    result = await tool.run({})

    assert source.focus.active.startedAt.isoformat() == "2026-08-31T02:00:00+00:00"
    assert result.data["focus"]["active"]["startedAt"] == "2026-08-31T10:00:00+08:00"
    assert result.data["focus"]["active"]["endedAt"] == "2026-08-31T11:00:00+08:00"
    assert result.metadata["display_timezone"] == "Asia/Shanghai"


def test_lifehud_display_timezone_rejects_unknown_zone():
    with pytest.raises(ValueError, match="未知 Life HUD 展示时区"):
        LifeHudClient("http://lifehud.test", display_timezone="Mars/Olympus")


def test_all_agent_context_tools_are_read_only_and_described():
    client = LifeHudClient("http://lifehud.test")
    tools = create_lifehud_context_tools(client)
    assert {tool.name for tool in tools} == {
        "lifehud_today", "lifehud_recent", "lifehud_status", "lifehud_focus",
        "lifehud_tasks", "lifehud_dreams", "lifehud_life", "lifehud_journal",
        "lifehud_media", "lifehud_growth",
    }
    assert all(not tool.mutates_state and tool.description for tool in tools)


async def test_all_agent_context_endpoints_parse_schema_one():
    base = {"schemaVersion": "1", "generatedAt": "2026-08-31T02:30:00Z"}
    payloads = {
        "/api/agent/context/recent": {**base, "startDate": "2026-08-25", "endDate": "2026-08-31", "days": 7, "lifeEventCount": 0, "focusMinutes": 0, "tasksCompleted": 0, "timeline": []},
        "/api/agent/context/status": {**base, "status": today_context()["status"]},
        "/api/agent/context/focus": focus_context(),
        "/api/agent/context/tasks": {**base, "date": "2026-08-31", "tasks": today_context()["tasks"]},
        "/api/agent/context/dreams": {**base, "dreams": today_context()["dreams"]},
        "/api/agent/context/life": {**base, "date": "2026-08-31", "life": {"sleep": None, "meals": [], "exercise": None, "checkIn": None, "records": []}},
        "/api/agent/context/journal": {**base, "entries": [], "timeline": []},
        "/api/agent/context/media": {**base, "media": today_context()["media"]},
        "/api/agent/context/growth": {**base, "growth": {"energy": 1, "exp": 2, "level": 3, "title": "铁幕行者", "recentEvents": [], "snapshots": []}},
    }

    def handler(request):
        return httpx.Response(200, json=payloads[request.url.path])

    client = LifeHudClient("http://lifehud.test", transport=httpx.MockTransport(handler))
    values = await asyncio.gather(
        client.recent(), client.status(), client.focus(), client.tasks(), client.dreams(),
        client.life(), client.journal(), client.media(), client.growth(),
    )
    assert all(value.schemaVersion == "1" for value in values)


async def test_unsupported_schema_is_not_parsed_as_fact():
    client = LifeHudClient(
        "http://lifehud.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=today_context(schemaVersion="2"))),
    )
    with pytest.raises(LifeHudError) as error:
        await client.today()
    assert error.value.code == "unsupported_schema_version"


async def test_400_detail_is_not_retried():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(400, json={"status": 400, "detail": "days 必须在 1 到 30 之间"})

    client = LifeHudClient("http://lifehud.test", transport=httpx.MockTransport(handler))
    with pytest.raises(LifeHudError, match="days 必须") as error:
        await client.recent(31)
    assert error.value.code == "lifehud_invalid_argument"
    assert len(requests) == 1


async def test_5xx_read_retries_but_write_does_not_replay():
    read_requests = []

    def read_handler(request):
        read_requests.append(request)
        return httpx.Response(503)

    client = LifeHudClient(
        "http://lifehud.test",
        max_retries=2,
        retry_backoff_seconds=0,
        transport=httpx.MockTransport(read_handler),
    )
    with pytest.raises(LifeHudError):
        await client.focus()
    assert len(read_requests) == 3

    write_requests = []

    def write_handler(request):
        write_requests.append(request)
        return httpx.Response(503)

    client = LifeHudClient(
        "http://lifehud.test",
        max_retries=2,
        retry_backoff_seconds=0,
        transport=httpx.MockTransport(write_handler),
    )
    with pytest.raises(LifeHudError):
        await client.start_iron_curtain("test", [])
    assert len(write_requests) == 1


async def test_offline_fails_without_guessing_facts():
    def handler(request):
        raise httpx.ConnectError("offline", request=request)

    client = LifeHudClient(
        "http://lifehud.test",
        max_retries=1,
        retry_backoff_seconds=0,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(LifeHudError) as error:
        await client.today()
    assert error.value.code == "lifehud_unavailable"


async def test_open_reads_context_writes_once_and_rereads_confirmation():
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            active = session() if sum(item.method == "GET" for item in requests) > 1 else None
            return httpx.Response(200, json=focus_context(active))
        assert json.loads(request.content) == {
            "mode": "IRON_CURTAIN",
            "title": "开发 v0.5.1",
            "taskId": None,
            "plannedMinutes": None,
            "breakMinutes": None,
            "relatedTaskIds": [],
        }
        return httpx.Response(200, json=session())

    runtime = runtime_for(handler)
    waiting = await runtime.start("lifehud.iron_curtain.open", {"title": "开发 v0.5.1"})
    assert waiting.status == WorkflowStatus.WAITING_FOR_PERMISSION
    completed = await runtime.approve(waiting.id)
    assert completed.result["outcome"] == "opened"
    assert [(item.method, item.url.path) for item in requests] == [
        ("GET", "/api/agent/context/focus"),
        ("POST", "/api/focus/start"),
        ("GET", "/api/agent/context/focus"),
    ]


async def test_open_does_not_duplicate_existing_focus():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=focus_context(session()))

    run = await runtime_for(handler).start("lifehud.iron_curtain.open", {"title": "重复"})
    assert run.result["outcome"] == "already_running"
    assert len(requests) == 1


async def test_close_reads_real_id_writes_once_and_confirms_absence():
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            active = session(session_id="real-id") if sum(item.method == "GET" for item in requests) == 1 else None
            return httpx.Response(200, json=focus_context(active))
        assert request.url.path == "/api/focus/real-id/complete"
        assert json.loads(request.content) == {"note": "完成握手"}
        return httpx.Response(200, json=session(status="COMPLETED", session_id="real-id"))

    runtime = runtime_for(handler)
    waiting = await runtime.start("lifehud.iron_curtain.close", {"note": "完成握手"})
    assert waiting.status == WorkflowStatus.WAITING_FOR_PERMISSION
    run = await runtime.approve(waiting.id)
    assert run.result["outcome"] == "closed"
    assert [item.method for item in requests] == ["GET", "POST", "GET"]


async def test_close_refuses_non_iron_curtain():
    def handler(request):
        return httpx.Response(200, json=focus_context(session(mode="POMODORO")))

    run = await runtime_for(handler).start("lifehud.iron_curtain.close", {"note": "完成"})
    assert run.result["outcome"] == "wrong_mode"


async def test_natural_open_and_approval_use_same_workflow_run():
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            active = session() if sum(item.method == "GET" for item in requests) > 1 else None
            return httpx.Response(200, json=focus_context(active))
        return httpx.Response(200, json=session())

    workflow = runtime_for(handler)
    provider = FakeProvider([ModelResponse(tool_calls=[ToolCall(
        id="route",
        name="route_cognition",
        arguments={
            "route": "workflow",
            "reason": "明确开幕命令",
            "workflow_id": "lifehud.iron_curtain.open",
            "workflow_inputs": {"title": "开发 v0.5.1"},
        },
    )])])
    agent = ZhaoxiAgent(
        provider=provider,
        registry=workflow.tool_executor.registry,
        context_builder=ContextBuilder("你是朝汐。"),
        conversation=Conversation(),
        tool_executor=workflow.tool_executor,
        workflow=workflow,
    )
    agent.cognitive = CognitiveCoordinator(agent=agent, router=CognitiveRouter(provider))
    waiting = await agent.run_natural("朝汐，开幕，开发 v0.5.1")
    assert waiting.route == CognitiveRoute.WORKFLOW and waiting.permission_confirmation
    completed = await agent.run_natural("允许")
    assert completed.request_id == waiting.workflow_run_id
    assert "铁幕已经开幕" in completed.content
    assert '"outcome"' not in completed.content


async def test_unknown_workflow_argument_is_ignored_without_crashing():
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            active = session() if sum(item.method == "GET" for item in requests) > 1 else None
            return httpx.Response(200, json=focus_context(active))
        return httpx.Response(200, json=session())

    runtime = runtime_for(handler)
    run = await runtime.start(
        "lifehud.iron_curtain.open",
        {"title": "专注测试", "note": "模型多提取的无害字段"},
        user_intent="开个铁幕专注测试一下",
    )
    assert run.status == WorkflowStatus.WAITING_FOR_PERMISSION
    assert run.inputs == {"title": "专注测试", "related_task_ids": []}
    assert run.ignored_inputs == ["note"]
    assert any(event.type == "unknown_inputs_ignored" for event in run.events)


async def test_permission_resume_returns_model_final_text_not_workflow_json():
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            active = session() if sum(item.method == "GET" for item in requests) > 1 else None
            return httpx.Response(200, json=focus_context(active))
        return httpx.Response(200, json=session())

    workflow = runtime_for(handler)
    provider = FakeProvider([
        ModelResponse(tool_calls=[ToolCall(
            id="route",
            name="route_cognition",
            arguments={
                "route": "workflow",
                "reason": "明确开幕命令",
                "workflow_id": "lifehud.iron_curtain.open",
                "workflow_inputs": {"title": "专注测试", "note": "多余"},
            },
        )]),
        ModelResponse(content="好，铁幕已经开幕。现在只做专注测试这一件事。"),
    ])
    agent = ZhaoxiAgent(
        provider=provider,
        registry=workflow.tool_executor.registry,
        context_builder=ContextBuilder("你是朝汐。"),
        conversation=Conversation(),
        tool_executor=workflow.tool_executor,
        workflow=workflow,
    )
    agent.cognitive = CognitiveCoordinator(agent=agent, router=CognitiveRouter(provider))
    waiting = await agent.run_natural("开个铁幕专注测试一下")
    completed = await agent.run_natural("确认")
    assert waiting.permission_confirmation is not None
    assert completed.content == "好，铁幕已经开幕。现在只做专注测试这一件事。"
    assert provider.tool_schemas[-1] is None
    assert "outcome" not in completed.content and "session" not in completed.content
    stored = await workflow.get(waiting.workflow_run_id)
    assert stored.user_intent == "开个铁幕专注测试一下"


async def test_invalid_workflow_input_returns_natural_error_boundary():
    workflow = runtime_for(lambda request: httpx.Response(200, json=focus_context()))
    provider = FakeProvider([ModelResponse(tool_calls=[ToolCall(
        id="route",
        name="route_cognition",
        arguments={
            "route": "workflow",
            "reason": "开幕",
            "workflow_id": "lifehud.iron_curtain.open",
            "workflow_inputs": {"title": {"bad": "shape"}},
        },
    )])])
    agent = ZhaoxiAgent(
        provider=provider,
        registry=workflow.tool_executor.registry,
        context_builder=ContextBuilder("你是朝汐。"),
        conversation=Conversation(),
        tool_executor=workflow.tool_executor,
        workflow=workflow,
    )
    agent.cognitive = CognitiveCoordinator(agent=agent, router=CognitiveRouter(provider))
    response = await agent.run_natural("开幕")
    assert "格式不正确" in response.content
    assert "Traceback" not in response.content and "WorkflowRuntimeError" not in response.content


async def test_natural_lifehud_query_really_calls_read_tool_and_returns_prose():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={
            "schemaVersion": "1",
            "generatedAt": "2026-08-31T02:30:00Z",
            "status": today_context()["status"],
        })

    client = LifeHudClient("http://lifehud.test", transport=httpx.MockTransport(handler))
    registry = ToolRegistry()
    for tool in create_lifehud_context_tools(client):
        registry.register(tool)
    provider = FakeProvider([
        ModelResponse(tool_calls=[ToolCall(
            id="route", name="route_cognition", arguments={"route": "tool", "reason": "查询 Life HUD"}
        )]),
        ModelResponse(content="我先检查一下 Life HUD。"),
        ModelResponse(tool_calls=[ToolCall(id="status", name="lifehud_status", arguments={})]),
        ModelResponse(content="Life HUD 当前连接正常，你现在是 17 级，Energy 122。"),
    ])
    agent = ZhaoxiAgent(
        provider=provider,
        registry=registry,
        context_builder=ContextBuilder("你是朝汐。"),
        conversation=Conversation(),
    )
    agent.cognitive = CognitiveCoordinator(agent=agent, router=CognitiveRouter(provider))
    response = await agent.run_natural("随便用 LifeHUD 查点啥")
    assert response.content == "Life HUD 当前连接正常，你现在是 17 级，Energy 122。"
    assert [item.url.path for item in requests] == ["/api/agent/context/status"]
    assert "schemaVersion" not in response.content and "{" not in response.content
    assert "必须调用一个最相关的可用工具" in provider.calls[2][0].content
