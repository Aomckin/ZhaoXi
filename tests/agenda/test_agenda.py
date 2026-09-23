from datetime import datetime, timedelta
import json
from zoneinfo import ZoneInfo

import httpx
import pytest

from zhaoxi.agenda import AgendaService, AgendaStatus, AgendaType, SQLiteAgendaStore
from zhaoxi.agenda.tools import create_agenda_tools
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.models.openai_compatible import OpenAICompatibleProvider
from zhaoxi.tools.registry import ToolRegistry
from zhaoxi.tools.router import resolve_tool_context
from zhaoxi.working_notes import SQLiteWorkingNotesStore, WorkingNotesService
from zhaoxi.working_notes.tools import create_working_notes_tools


ZONE = ZoneInfo("Asia/Shanghai")


def service(tmp_path, now):
    return AgendaService(SQLiteAgendaStore(tmp_path / "agenda.db"), clock=lambda: now, max_context_items=6)


def test_all_types_persist_and_duplicate_updates(tmp_path):
    now = datetime(2026, 9, 22, 10, tzinfo=ZONE)
    agenda = service(tmp_path, now)
    event, created = agenda.add(type=AgendaType.EVENT, title="线下面试", start_at=now + timedelta(hours=4))
    assert created
    agenda.add(type=AgendaType.WINDOW, title="整理网申", start_at=now, end_at=now + timedelta(hours=2))
    agenda.add(type=AgendaType.DEADLINE, title="交 README", due_at=now + timedelta(days=1))
    agenda.add(type=AgendaType.FOCUS, title="完成 v1.2.6", scope="today")
    agenda.add(type=AgendaType.EXPECTATION, title="优化 Life HUD", condition="今晚有精力")
    duplicate, created = agenda.add(type=AgendaType.EVENT, title="线下面试", start_at=now + timedelta(hours=5))
    assert not created and duplicate.id == event.id
    restored = AgendaService(SQLiteAgendaStore(tmp_path / "agenda.db"), clock=lambda: now)
    assert len(restored.list("active")) == 5
    assert restored.require(event.id).start_at.hour == 15


def test_lifecycle_and_expired_event_not_upcoming(tmp_path):
    now = datetime(2026, 9, 22, 21, 30, tzinfo=ZONE)
    agenda = service(tmp_path, now)
    past, _ = agenda.add(type=AgendaType.EVENT, title="宣讲会", start_at=now - timedelta(hours=2))
    active, _ = agenda.add(type=AgendaType.WINDOW, title="整理材料", start_at=now - timedelta(hours=1), end_at=now + timedelta(hours=1))
    done, _ = agenda.add(type=AgendaType.DEADLINE, title="提交", due_at=now + timedelta(days=1))
    cancelled, _ = agenda.add(type=AgendaType.EXPECTATION, title="看看资料")
    upcoming = agenda.list("upcoming")
    assert past.id not in {item.id for item in upcoming}
    assert agenda.require(past.id).status is AgendaStatus.MISSED
    assert agenda.require(active.id).status is AgendaStatus.ACTIVE
    assert agenda.complete(done.id).status is AgendaStatus.DONE
    assert agenda.cancel(cancelled.id).status is AgendaStatus.CANCELLED
    snapshot = agenda.snapshot()
    assert "21:30" in snapshot and "宣讲会" not in snapshot and len(snapshot) < 1000


def test_invalid_type_time_contract(tmp_path):
    agenda = service(tmp_path, datetime(2026, 9, 22, tzinfo=ZONE))
    with pytest.raises(ValueError):
        agenda.add(type=AgendaType.EVENT, title="没有时间")


@pytest.mark.parametrize("message, expected", [
    ("明天下午三点有个面试。", "agenda"),
    ("今天主线就先把朝汐 1.2.6 做了。", "agenda"),
    ("这个问题先记着，之后再修。", "working_notes"),
])
def test_natural_language_routes_relevant_tool_group(tmp_path, message, expected):
    agenda = service(tmp_path, datetime(2026, 9, 22, tzinfo=ZONE))
    notes = WorkingNotesService(SQLiteWorkingNotesStore(tmp_path / "notes.db"))
    registry = ToolRegistry()
    for tool in (*create_agenda_tools(agenda), *create_working_notes_tools(notes)):
        registry.register(tool)
    context = resolve_tool_context(message, [], registry)
    assert expected in context.dynamic_groups


async def test_text_control_calls_do_not_corrupt_agenda_tool_transcript(tmp_path):
    payloads = []
    responses = iter([
        '<|DSML|tool_calls><|DSML|invoke name="inspect_tool_catalog">'
        '<|DSML|parameter name="action">inspect_group</|DSML|parameter>'
        '<|DSML|parameter name="group">agenda</|DSML|parameter>'
        '</|DSML|invoke></|DSML|tool_calls>',
        '<|DSML|tool_calls><|DSML|invoke name="request_tool_group">'
        '<|DSML|parameter name="group">agenda</|DSML|parameter>'
        '</|DSML|invoke></|DSML|tool_calls>',
        '<|DSML|tool_calls><|DSML|invoke name="agenda_add">'
        '<|DSML|parameter name="type">event</|DSML|parameter>'
        '<|DSML|parameter name="title">AI+创新产业大会</|DSML|parameter>'
        '<|DSML|parameter name="start_at">2026-09-24T14:00:00+08:00</|DSML|parameter>'
        '</|DSML|invoke></|DSML|tool_calls>',
        "两条链路已经完整执行。",
    ])

    async def handler(request):
        payload = json.loads(request.content)
        payloads.append(payload)
        content = next(responses)
        return httpx.Response(200, json={
            "id": f"response-{len(payloads)}",
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        })

    agenda = service(tmp_path, datetime(2026, 9, 22, 23, 29, tzinfo=ZONE))
    registry = ToolRegistry()
    for tool in create_agenda_tools(agenda):
        registry.register(tool)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatibleProvider(
            base_url="https://example.test/v1", api_key="test", model="deepseek-v4-flash", client=client,
        )
        agent = ZhaoxiAgent(provider=provider, registry=registry, context_builder=ContextBuilder("朝汐"))
        result = await agent.run("请处理图片里的安排", require_tool_call=True)

    assert result.content == "两条链路已经完整执行。"
    for payload in payloads[1:3]:
        assert not any(message["role"] == "tool" for message in payload["messages"])
        assert not any(message.get("tool_calls") for message in payload["messages"])
    assert payloads[3]["messages"][-2]["role"] == "assistant"
    assert "tool_calls" not in payloads[3]["messages"][-2]
    assert "Internal tool calls requested: agenda_add" in payloads[3]["messages"][-2]["content"]
    assert payloads[3]["messages"][-1]["role"] == "user"
    assert "Internal tool result for agenda_add" in payloads[3]["messages"][-1]["content"]
    assert agenda.list("upcoming")[0].title == "AI+创新产业大会"
