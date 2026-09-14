import httpx
from datetime import UTC, datetime

from tools.lifehud_tool import LifeHudClient, LifeHudTool
from zhaoxi.permission.executor import ToolExecutor
from zhaoxi.permission.models import InvocationOrigin
from zhaoxi.tools.packages import create_package_tools, discover_tool_packages
from zhaoxi.tools.registry import ToolRegistry
from zhaoxi.reflection.models import ReflectionKind
from zhaoxi.reflection.periods import PeriodResolver
from tools.lifehud_tool.reflection import LifeHudReflectionSource


def _status_payload():
    return {
        "schemaVersion": "1",
        "generatedAt": "2026-09-01T12:00:00Z",
        "status": {"energy": 100, "level": 1, "exp": 0, "title": "test", "checkIn": None, "activeFocus": None},
    }


def test_discovery_exposes_exactly_one_lifehud_tool():
    packages = [item for item in discover_tool_packages() if item.package_id == "lifehud-tool"]
    assert len(packages) == 1
    assert [tool.name for tool in create_package_tools(packages[0])] == ["lifehud"]


def test_lifehud_manifest_describes_natural_language_intents():
    registry = ToolRegistry()
    registry.register(LifeHudTool(None))
    record = registry.manifest()[0]
    assert record["group"] == "lifehud"
    assert {"评价今天饮食", "查询睡眠记录", "查询任务完成情况", "查看近期生活状态"} <= set(record["intents"])


async def test_one_tool_resolves_read_and_write_permissions_per_invocation():
    client = LifeHudClient(
        "http://lifehud.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=_status_payload())),
    )
    registry = ToolRegistry()
    registry.register(LifeHudTool(client))
    executor = ToolExecutor(registry)

    read = await executor.execute(
        "lifehud",
        {"operation": "context.status", "arguments": {}},
        request_id="read",
        invocation_id="read-call",
        origin=InvocationOrigin.AGENT,
    )
    write = await executor.execute(
        "lifehud",
        {"operation": "focus.start", "arguments": {"title": "测试", "related_task_ids": []}},
        request_id="write",
        invocation_id="write-call",
        origin=InvocationOrigin.AGENT,
    )

    assert read.result is not None and read.result.success
    assert read.request.permission.value == "read"
    assert write.waiting_for_permission
    assert write.request.permission.value == "write"


async def test_reflection_source_uses_public_recent_context_and_maps_evidence():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={
            "schemaVersion": "1",
            "generatedAt": "2026-09-01T12:00:00Z",
            "startDate": "2026-09-01",
            "endDate": "2026-09-01",
            "days": 1,
            "lifeEventCount": 1,
            "focusMinutes": 30,
            "tasksCompleted": 1,
            "timeline": [{
                "eventId": "event-1",
                "type": "focus.completed",
                "source": "focus",
                "occurredAt": "2026-09-01T12:00:00Z",
                "title": "完成开发",
                "summary": "完成 Reflection 接线",
            }],
        })

    client = LifeHudClient(
        "http://lifehud.test", transport=httpx.MockTransport(handler)
    )
    period = PeriodResolver("UTC").resolve(
        ReflectionKind.DAILY, reference=datetime(2026, 9, 1, tzinfo=UTC)
    )
    snapshot = await LifeHudReflectionSource(client).collect(period)

    assert len(snapshot.evidence) == 1
    assert snapshot.evidence[0].source_name == "lifehud"
    assert snapshot.evidence[0].source_record_id == "event-1"
    assert seen[0].method == "GET"
    assert seen[0].url.path == "/api/agent/context/recent"
