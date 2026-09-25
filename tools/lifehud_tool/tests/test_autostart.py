"""Life HUD on-demand startup never replays an uncertain create."""

import asyncio
import os
from pathlib import Path

import httpx
import pytest

from tools.lifehud_tool.client import LifeHudClient
from tools.lifehud_tool.errors import LifeHudError
from tools.lifehud_tool.package import LifeHudToolPackage


@pytest.fixture
def anyio_backend():
    return "asyncio"


STATUS = {"schemaVersion": "1", "generatedAt": "2026-09-24T00:00:00Z",
          "status": {"energy": 1, "level": 1, "exp": 0, "title": "", "checkIn": None, "activeFocus": None}}


class RunningProcess:
    def poll(self):
        return None


def client(handler, launcher, **kwargs):
    return LifeHudClient("http://127.0.0.1:8025", transport=httpx.MockTransport(handler),
                         autostart=True, autostart_launcher=launcher,
                         startup_timeout_seconds=0.12, startup_poll_seconds=0.05,
                         retry_backoff_seconds=0, **kwargs)


@pytest.mark.anyio
async def test_healthy_service_is_probed_once_without_launch():
    paths = []
    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json=STATUS)
    instance = client(handler, lambda: pytest.fail("launcher called"))
    await instance.status()
    await instance.status()
    assert paths == ["/api/agent/context/status"] * 3


@pytest.mark.anyio
async def test_local_probe_and_request_ignore_environment_proxy(monkeypatch):
    original = httpx.AsyncClient
    trust_settings = []
    def recording_client(*args, **kwargs):
        trust_settings.append(kwargs.get("trust_env"))
        return original(*args, **kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", recording_client)
    instance = client(lambda request: httpx.Response(200, json=STATUS),
                      lambda: pytest.fail("launcher called"))
    await instance.status()
    assert trust_settings == [False, False]


@pytest.mark.anyio
async def test_refused_connection_starts_once_and_retries_original_read():
    attempts = 0
    launches = 0
    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("Connection refused", request=request)
        return httpx.Response(200, json=STATUS)
    def launch():
        nonlocal launches
        launches += 1
        return RunningProcess()
    instance = client(handler, launch)
    await asyncio.gather(instance.status(), instance.status())
    assert launches == 1 and attempts == 4  # refused probe, ready probe, two reads


@pytest.mark.anyio
async def test_connect_timeout_starts_and_retries_original_read():
    attempts = 0
    launches = 0
    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectTimeout("timed out", request=request)
        return httpx.Response(200, json=STATUS)
    def launch():
        nonlocal launches
        launches += 1
        return RunningProcess()
    await client(handler, launch).status()
    assert launches == 1 and attempts == 3


@pytest.mark.anyio
async def test_refused_post_connection_retries_once_after_start():
    post_attempts = 0
    probes = 0
    launches = 0
    def handler(request):
        nonlocal post_attempts, probes
        if request.method == "GET":
            probes += 1
            if probes == 2:
                raise httpx.ConnectError("Connection refused", request=request)
            return httpx.Response(200, json=STATUS)
        post_attempts += 1
        if post_attempts == 1:
            raise httpx.ConnectError("Connection refused", request=request)
        return httpx.Response(201, json={"id": "one"})
    def launch():
        nonlocal launches
        launches += 1
        return RunningProcess()
    result = await client(handler, launch).request_json("POST", "/api/life/meals", body={"description": "晚饭"})
    assert result == {"id": "one"}
    assert launches == 1 and post_attempts == 2 and probes == 3


@pytest.mark.anyio
async def test_connect_timeout_on_post_retries_once_after_start():
    posts = 0
    probes = 0
    launches = 0
    def handler(request):
        nonlocal posts, probes
        if request.method == "GET":
            probes += 1
            if probes == 2:
                raise httpx.ConnectTimeout("timed out", request=request)
            return httpx.Response(200, json=STATUS)
        posts += 1
        if posts == 1:
            raise httpx.ConnectTimeout("timed out", request=request)
        return httpx.Response(201, json={"id": "one"})
    def launch():
        nonlocal launches
        launches += 1
        return RunningProcess()
    result = await client(handler, launch).request_json("POST", "/api/life/meals", body={"description": "晚饭"})
    assert result == {"id": "one"}
    assert launches == 1 and posts == 2 and probes == 3


@pytest.mark.anyio
async def test_read_timeout_with_open_port_does_not_launch_or_retry_post(monkeypatch):
    async def port_open():
        return True
    monkeypatch.setattr("tools.lifehud_tool.autostart.LifeHudAutoStarter._tcp_port_open", lambda self: port_open())
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)
    with pytest.raises(LifeHudError, match="健康接口读取超时") as error:
        await client(handler, lambda: pytest.fail("launcher called")).request_json("POST", "/api/life/meals")
    assert error.value.code == "lifehud_unavailable"


@pytest.mark.anyio
async def test_read_timeout_with_closed_port_starts_service(monkeypatch):
    async def port_open():
        return False
    monkeypatch.setattr("tools.lifehud_tool.autostart.LifeHudAutoStarter._tcp_port_open", lambda self: port_open())
    attempts = 0
    launches = 0
    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(200, json=STATUS)
    def launch():
        nonlocal launches
        launches += 1
        return RunningProcess()
    await client(handler, launch).status()
    assert launches == 1 and attempts == 3


@pytest.mark.anyio
async def test_post_timeout_after_healthy_probe_is_not_replayed():
    posts = 0
    def handler(request):
        nonlocal posts
        if request.method == "GET":
            return httpx.Response(200, json=STATUS)
        posts += 1
        raise httpx.ReadTimeout("write outcome unknown", request=request)
    with pytest.raises(LifeHudError) as error:
        await client(handler, lambda: pytest.fail("launcher called")).request_json(
            "POST", "/api/life/meals", body={"description": "晚饭"})
    assert error.value.code == "lifehud_unavailable"
    assert posts == 1


@pytest.mark.anyio
async def test_http_failure_and_wrong_schema_do_not_launch():
    for response in (httpx.Response(503), httpx.Response(200, json={"schemaVersion": "2"})):
        instance = client(lambda request: response, lambda: pytest.fail("launcher called"))
        with pytest.raises(LifeHudError):
            await instance.status()


@pytest.mark.anyio
async def test_launcher_failure_and_ready_timeout_have_distinct_errors():
    def refused(request):
        raise httpx.ConnectError("Connection refused", request=request)
    def missing():
        raise FileNotFoundError("mvnw.cmd missing")
    with pytest.raises(LifeHudError, match="mvnw.cmd missing") as missing_error:
        await client(refused, missing).status()
    assert missing_error.value.code == "lifehud_start_failed"
    with pytest.raises(LifeHudError, match="仍未就绪") as timeout_error:
        await client(refused, RunningProcess).status()
    assert timeout_error.value.code == "lifehud_start_timeout"

    class ExitedProcess:
        def poll(self):
            return 7
    with pytest.raises(LifeHudError, match="exit=7") as exited_error:
        await client(refused, ExitedProcess).status()
    assert exited_error.value.code == "lifehud_start_failed"


def test_windows_launcher_uses_background_maven_wrapper(tmp_path, monkeypatch):
    from tools.lifehud_tool.autostart import LifeHudAutoStarter
    project = tmp_path / "Life HUD"
    project.mkdir()
    (project / ("mvnw.cmd" if os.name == "nt" else "mvnw")).write_text("stub")
    monkeypatch.chdir(tmp_path)
    captured = {}
    def fake_popen(command, **kwargs):
        captured.update(command=command, **kwargs)
        return RunningProcess()
    monkeypatch.setattr("tools.lifehud_tool.autostart.subprocess.Popen", fake_popen)
    starter = LifeHudAutoStarter(base_url="http://127.0.0.1:8025", context_path="/api/agent/context",
                                 schema_version="1", project_dir=project)
    starter._launch_process()
    assert captured["cwd"] == project.resolve()
    assert "spring-boot:run" in captured["command"]
    assert captured["stdin"] is not None and captured["stdout"] is not None
    if os.name == "nt":
        assert captured["creationflags"] & __import__("subprocess").CREATE_NO_WINDOW
    assert (tmp_path / "data/logs/lifehud-autostart.log").exists()


def test_autostart_is_limited_to_local_default_service():
    package = LifeHudToolPackage()
    package.configure({"base_url": "http://127.0.0.1:8025", "autostart_enabled": "false"})
    assert package.client.autostarter is None
    package.configure({"base_url": "https://lifehud.example.com:8025"})
    assert package.client.autostarter is None
    package.configure({"base_url": "http://127.0.0.1:8025"})
    assert package.client.autostarter is not None
