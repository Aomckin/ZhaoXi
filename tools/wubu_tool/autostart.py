"""Start Wubu through its documented startup script after refused connects."""
import errno
import math
import os
from pathlib import Path
import subprocess
import threading
import time
from urllib.error import URLError

from tools.wubu_tool.client import WubuClient, WubuError


def connection_refused(exc):
    """Use OS error codes; a timeout/reset does not prove a request was unsent."""
    seen = set()
    while isinstance(exc, BaseException) and id(exc) not in seen:
        seen.add(id(exc))
        if (isinstance(exc, ConnectionRefusedError)
                or getattr(exc, "errno", None) in {errno.ECONNREFUSED, 10061}
                or getattr(exc, "winerror", None) == 10061):
            return True
        exc = exc.reason if isinstance(exc, URLError) else exc.__cause__
    return False


class WubuAutoStarter:
    # Different tool instances in the same process share the launch guard.
    _guard = threading.Lock()
    _locks = {}
    _processes = {}

    def __init__(self, base_url, project_dir=None, timeout=8, poll_interval=0.2):
        self.base_url = base_url
        self.project_dir = Path(project_dir) if project_dir else Path(__file__).resolve().parents[3] / "物簿"
        self.timeout = float(timeout)
        self.poll_interval = float(poll_interval)
        if any(not math.isfinite(v) or v <= 0 for v in (self.timeout, self.poll_interval)):
            raise ValueError("物簿启动等待时间和轮询间隔必须是有限正数。")
        self.identity = (base_url, str(self.project_dir.resolve()))
        with self._guard:
            self._lock = self._locks.setdefault(self.identity, threading.Lock())

    def _probe(self, timeout=0.4):
        data, _ = WubuClient(self.base_url, timeout=timeout).request("GET", "/healthz")
        if not isinstance(data, dict) or data.get("status") != "ok" or data.get("database") != "ok":
            raise WubuError("wubu_unhealthy", "物簿尚未健康就绪。")

    def _launch(self):
        script = self.project_dir / "scripts" / "start.ps1"
        if not script.is_file():
            raise WubuError("wubu_start_failed", f"物簿启动脚本不存在：{script}")
        if os.name != "nt":
            raise WubuError("wubu_start_failed", "物簿自动启动脚本需要 Windows PowerShell。")
        return subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            cwd=str(self.project_dir), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def ensure_ready(self):
        with self._lock:
            try:
                # Windows can take roughly two seconds to report WSAECONNREFUSED.
                self._probe(timeout=min(3, self.timeout))
                return
            except WubuError as exc:
                # Another service or an unhealthy Wubu is already listening: do not spawn.
                if not getattr(exc, "refused", False):
                    raise
            process = self._processes.get(self.identity)
            if process is None or process.poll() is not None:
                try:
                    process = self._launch()
                except OSError as exc:
                    raise WubuError("wubu_start_failed", f"物簿自动启动失败：{exc}") from exc
                self._processes[self.identity] = process
            deadline = time.monotonic() + self.timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise WubuError("wubu_start_timeout", f"物簿启动后 {self.timeout:g} 秒仍未就绪。", retryable=True)
                try:
                    self._probe(timeout=min(0.4, remaining))
                    return
                except WubuError:
                    pass
                exit_code = process.poll()
                # A startup script can successfully detach the actual service and exit zero.
                if exit_code is not None and exit_code != 0:
                    raise WubuError("wubu_start_failed", f"物簿启动脚本退出，exit={exit_code}。")
                time.sleep(min(self.poll_interval, max(0, deadline - time.monotonic())))
