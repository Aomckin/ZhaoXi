"""Contract tests for the public Life HUD adapter."""

import httpx
import pytest

from tools.lifehud_tool.client import LifeHudClient
from tools.lifehud_tool.tool import LifeHudTool
from tools.lifehud_tool.package import LifeHudToolPackage


@pytest.fixture
def anyio_backend():
    return "asyncio"


def make_tool(handler, **enabled):
    return LifeHudTool(LifeHudClient("http://lifehud.test", transport=httpx.MockTransport(handler),
                                     retry_backoff_seconds=0), enabled)


@pytest.mark.anyio
@pytest.mark.parametrize("kind,path,payload", [
    ("sleep", "/api/life/sleep", {"sleepTime": "2026-09-23T02:00:00+08:00", "wakeTime": "2026-09-23T08:30:00+08:00", "quality": 3, "sleepType": "NIGHT"}),
    ("meal", "/api/life/meals", {"time": "2026-09-23T19:00:00+08:00", "description": "晚饭"}),
    ("exercise", "/api/life/exercises", {"exerciseType": "CYCLING", "startTime": "2026-09-23T18:00:00+08:00", "durationMinutes": 60}),
    ("check_in", "/api/life/check-ins", {"energy": 3, "mood": 4, "time": "2026-09-23T18:00:00+08:00"}),
    ("life_record", "/api/life/records", {"recordType": "CAFFEINE", "value": 1, "unit": "cup", "time": "2026-09-23T14:00:00+08:00"}),
])
async def test_record_create_and_readback(kind, path, payload):
    seen = []
    def handler(request):
        seen.append(request)
        if request.method == "POST":
            return httpx.Response(201, json={"id": "new-1", **__import__("json").loads(request.content)})
        return httpx.Response(200, json={"id": "new-1", "saved": True})
    result = await make_tool(handler).run({"operation": "record", "arguments": {"action": "create", "type": kind, **payload}})
    assert result.success and result.data["data"]["record"]["saved"]
    assert [(r.method, r.url.path) for r in seen] == [("POST", path), ("GET", path + "/new-1")]
    body = __import__("json").loads(seen[0].content)
    if kind == "exercise": assert body["type"] == "CYCLING"
    if kind == "sleep": assert body["type"] == "NIGHT"
    if kind == "life_record": assert body["type"] == "CAFFEINE"


@pytest.mark.anyio
@pytest.mark.parametrize("images", [None, []])
async def test_update_image_semantics(images):
    bodies = []
    def handler(request):
        if request.method == "PUT": bodies.append(__import__("json").loads(request.content))
        return httpx.Response(200, json={"id": "one", "images": ["/uploads/old.png"]})
    args = {"action": "update", "type": "meal", "id": "one", "note": "好吃"}
    if images is not None: args["images"] = images
    result = await make_tool(handler).run({"operation": "record", "arguments": args})
    assert result.success
    assert ("images" in bodies[0]) is (images is not None)
    if images is not None: assert bodies[0]["images"] == []


@pytest.mark.anyio
async def test_image_upload_then_meal_and_journal(tmp_path):
    image = tmp_path / "dinner.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"image")
    calls = []
    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/images": return httpx.Response(200, json={"path": "/uploads/hash.png"})
        if request.method == "POST":
            body = __import__("json").loads(request.content)
            assert body["images"] == ["/uploads/hash.png"]
            return httpx.Response(201, json={"id": "one"})
        return httpx.Response(200, json={"id": "one", "images": ["/uploads/hash.png"]})
    tool = make_tool(handler)
    for operation, extra in [("record", {"type": "meal", "description": "晚饭"}),
                             ("journal", {"content": "今日晚餐"})]:
        result = await tool.run({"operation": operation, "arguments": {"action": "create", "images": [str(image)], **extra}})
        assert result.success
    assert calls.count(("POST", "/api/images")) == 2


@pytest.mark.anyio
async def test_failed_create_is_not_retried_and_uploaded_image_is_reported(tmp_path):
    image = tmp_path / "a.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"image")
    calls = []
    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/api/images": return httpx.Response(200, json={"path": "/uploads/a.png"})
        raise httpx.ConnectError("lost")
    result = await make_tool(handler).run({"operation": "record", "arguments": {"type": "meal", "images": [str(image)]}})
    assert not result.success
    assert calls == ["/api/images", "/api/life/meals"]
    assert result.data["warnings"] == ["image_uploaded_but_record_failed"]


@pytest.mark.anyio
async def test_destructive_and_inferred_check_in_do_not_hit_network():
    def handler(request):
        pytest.fail("unexpected network request")
    tool = make_tool(handler)
    for args in ({"type": "meal", "action": "delete", "id": "one"},
                 {"type": "check_in", "action": "create", "source": "inferred"}):
        result = await tool.run({"operation": "record", "arguments": args})
        assert not result.success
    assert tool.permission_for({"operation": "record", "arguments": {"action": "delete"}}).value == "delete"


@pytest.mark.anyio
async def test_bad_image_blocks_business_write(tmp_path):
    image = tmp_path / "a.txt"
    image.write_text("not an image")
    result = await make_tool(lambda request: pytest.fail("network request")).run(
        {"operation": "record", "arguments": {"type": "meal", "images": [str(image)]}})
    assert result.error == "unsupported_image"


@pytest.mark.anyio
async def test_current_message_placeholder_without_attachment_fails_closed():
    result = await make_tool(lambda request: pytest.fail("network request")).run({
        "operation": "record", "arguments": {"type": "meal", "images": ["<current-message-image>"]},
    })
    assert result.error == "attachment_not_found"


@pytest.mark.anyio
async def test_two_images_upload_before_create(tmp_path):
    images = []
    for name in ("first.png", "second.png"):
        path = tmp_path / name
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + name.encode())
        images.append(str(path))
    calls = []
    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/api/images":
            return httpx.Response(200, json={"path": f"/uploads/{len(calls)}.png"})
        if request.method == "POST":
            body = __import__("json").loads(request.content)
            assert body["images"] == ["/uploads/1.png", "/uploads/2.png"]
            return httpx.Response(201, json={"id": "one"})
        return httpx.Response(200, json={"id": "one"})
    result = await make_tool(handler).run({"operation": "record", "type": "meal", "images": images})
    assert result.success
    assert calls == ["/api/images", "/api/images", "/api/life/meals", "/api/life/meals/one"]


@pytest.mark.anyio
async def test_focus_conflict_and_media_session_confirmation():
    def conflict(request):
        return httpx.Response(409, json={"detail": "invalid state"})
    result = await make_tool(conflict).run({"operation": "focus", "arguments": {"action": "pause", "id": "one"}})
    assert result.error == "lifehud_conflict"

    calls = []
    def media(request):
        calls.append((request.method, request.url.path))
        if request.method == "POST": return httpx.Response(201, json={"id": "session-1"})
        return httpx.Response(200, json=[{"id": "session-1", "episodeEnd": 2}])
    result = await make_tool(media).run({"operation": "media", "arguments": {
        "action": "create", "type": "anime_session", "parentId": "anime-1", "episodeStart": 1,
        "episodeEnd": 2, "watchedAt": "2026-09-24T22:00:00+08:00"}})
    assert result.success and result.data["data"]["record"]["episodeEnd"] == 2
    assert calls == [("POST", "/api/media/anime/anime-1/sessions"),
                     ("GET", "/api/media/anime/anime-1/sessions")]


@pytest.mark.anyio
async def test_package_write_flag_and_duplicate_image_paths(tmp_path):
    package = LifeHudToolPackage()
    disabled = package.create_tools({"base_url": "http://lifehud.test", "write_enabled": "false"})[0]
    assert disabled.default_confirm_write is False
    blocked = await disabled.run({"operation": "record", "arguments": {"type": "meal"}})
    assert blocked.error == "capability_disabled"

    image = tmp_path / "same.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"same")
    calls = []
    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/api/images": return httpx.Response(200, json={"path": "/uploads/hash.png"})
        if request.method == "POST":
            assert __import__("json").loads(request.content)["images"] == ["/uploads/hash.png", "/uploads/hash.png"]
            return httpx.Response(201, json={"id": "one"})
        return httpx.Response(200, json={"id": "one"})
    result = await make_tool(handler).run({"operation": "record", "arguments": {
        "type": "meal", "images": [str(image), str(image)]}})
    assert result.success and calls.count("/api/images") == 2
