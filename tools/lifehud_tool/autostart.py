"""Start the local Life HUD service when a TCP connection cannot be established."""

import asyncio
import errno
import logging
import os
from pathlib import Path
import subprocess
import time
from typing import Callable
from urllib.parse import urlparse

import httpx

from tools.lifehud_tool.errors import LifeHudError, UnsupportedSchemaVersion


logger = logging.getLogger("LIFEHUD")


def connection_refused(exc: BaseException) -> bool:
    """A refused TCP connect is safe to retry; other network failures are not."""
    if not isinstance(exc, httpx.ConnectError):
        return False
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, ConnectionRefusedError) or getattr(current, "errno", None) in {
            errno.ECONNREFUSED, 10061,
        }:
            return True
        current = current.__cause__
    message = str(exc).casefold()
    return "connection refused" in message or "actively refused" in message


def connection_unavailable(exc: BaseException) -> bool:
    """A failed TCP connect cannot have sent the original request."""
    return isinstance(exc, httpx.ConnectTimeout) or connection_refused(exc)


def local_lifehud_url(base_url: str) -> bool:
    parsed = urlparse(base_url)
    return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"} and parsed.port == 8025


class LifeHudAutoStarter:
    def __init__(self, *, base_url: str, context_path: str, schema_version: str,
                 project_dir: str | Path, timeout_seconds: float = 8,
                 poll_interval_seconds: float = 0.4, probe_timeout_seconds: float = 0.4,
                 transport: httpx.AsyncBaseTransport | None = None,
                 launcher: Callable[[], object] | None = None) -> None:
        self.base_url = base_url
        self.context_path = context_path
        self.schema_version = schema_version
        self.project_dir = Path(project_dir)
        self.timeout_seconds = max(0.1, timeout_seconds)
        self.poll_interval_seconds = max(0.05, poll_interval_seconds)
        self.probe_timeout_seconds = max(0.05, probe_timeout_seconds)
        self.transport = transport
        self.launcher = launcher or self._launch_process
        self.log_path = Path.cwd() / "data" / "logs" / "lifehud-autostart.log"
        self._lock = asyncio.Lock()
        self._ready = False
        self._process = None

    def mark_unready(self) -> None:
        self._ready = False

    async def ensure_ready(self) -> None:
        if self._ready:
            return
        async with self._lock:
            if self._ready:
                return
            try:
                await self._probe()
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                logger.warning("health probe connection failed type=%s detail=%r", type(exc).__name__, str(exc))
                if not connection_unavailable(exc):
                    raise LifeHudError("Life HUD 网络连接失败；未触发自动启动。",
                                       code="lifehud_unavailable") from exc
            except httpx.ReadTimeout as exc:
                logger.warning("health probe read timed out detail=%r", str(exc))
                if await self._tcp_port_open():
                    raise LifeHudError("Life HUD 健康接口读取超时；服务端口仍可连接，未重复启动。",
                                       code="lifehud_unavailable") from exc
                logger.info("Life HUD port is unreachable after read timeout; starting service")
            except httpx.TimeoutException as exc:
                logger.warning("health probe timed out type=%s detail=%r", type(exc).__name__, str(exc))
                raise LifeHudError("Life HUD 健康探测超时；未触发自动启动。",
                                   code="lifehud_unavailable") from exc
            else:
                self._ready = True
                return
            if self._process is None or self._process.poll() is not None:
                try:
                    logger.info("starting Life HUD project=%s", self.project_dir)
                    self._process = await asyncio.to_thread(self.launcher)
                except (OSError, ValueError) as exc:
                    logger.error("Life HUD launcher failed type=%s detail=%r", type(exc).__name__, str(exc))
                    raise LifeHudError(f"Life HUD 自动启动失败：{exc}", code="lifehud_start_failed") from exc
            deadline = time.monotonic() + self.timeout_seconds
            last_error = "服务尚未就绪"
            while True:
                try:
                    await self._probe()
                except (httpx.ConnectError, httpx.TimeoutException) as exc:
                    last_error = "服务仍未接受连接" if connection_unavailable(exc) else "健康探测超时或连接异常"
                except LifeHudError as exc:
                    if exc.code == "unsupported_schema_version":
                        raise
                    last_error = str(exc)
                else:
                    self._ready = True
                    return
                if self._process is not None and (exit_code := self._process.poll()) is not None:
                    # Another process might have won the port race; probe once more before reporting exit.
                    try:
                        await self._probe()
                    except (httpx.HTTPError, LifeHudError):
                        raise LifeHudError(
                            f"Life HUD 启动进程提前退出（exit={exit_code}）；{last_error}。日志：{self.log_path}",
                            code="lifehud_start_failed",
                        )
                    self._ready = True
                    return
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise LifeHudError(
                        f"Life HUD 启动后 {self.timeout_seconds:g} 秒仍未就绪；{last_error}。日志：{self.log_path}",
                        code="lifehud_start_timeout",
                    )
                await asyncio.sleep(min(self.poll_interval_seconds, remaining))

    async def _tcp_port_open(self) -> bool:
        parsed = urlparse(self.base_url)
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(parsed.hostname, parsed.port),
                timeout=self.probe_timeout_seconds,
            )
        except (OSError, TimeoutError):
            return False
        writer.close()
        return True

    async def _probe(self) -> None:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.probe_timeout_seconds,
                                     transport=self.transport, trust_env=False) as client:
            response = await client.get(f"{self.context_path}/status")
        if response.status_code >= 400:
            raise LifeHudError(f"Life HUD 健康接口返回 HTTP {response.status_code}。",
                               code="lifehud_health_failed")
        try:
            payload = response.json()
        except ValueError as exc:
            raise LifeHudError("Life HUD 健康接口返回无效 JSON。",
                               code="invalid_lifehud_response") from exc
        actual = payload.get("schemaVersion") if isinstance(payload, dict) else None
        if actual != self.schema_version:
            raise UnsupportedSchemaVersion(actual, self.schema_version)

    def _launch_process(self) -> subprocess.Popen:
        project = self.project_dir.resolve()
        wrapper = project / ("mvnw.cmd" if os.name == "nt" else "mvnw")
        if not project.is_dir() or not wrapper.is_file():
            raise FileNotFoundError(f"未找到 Life HUD Maven Wrapper：{wrapper}")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        command = ([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", "mvnw.cmd", "spring-boot:run"]
                   if os.name == "nt" else [str(wrapper), "spring-boot:run"])
        flags = (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
        with self.log_path.open("ab") as output:
            return subprocess.Popen(command, cwd=project, stdin=subprocess.DEVNULL,
                                    stdout=output, stderr=subprocess.STDOUT,
                                    creationflags=flags, start_new_session=os.name != "nt")
