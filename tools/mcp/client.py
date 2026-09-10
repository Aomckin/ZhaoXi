"""Small stdio MCP client. No MCP dependency crosses into Zhaoxi Core."""

from __future__ import annotations

import json
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
from threading import RLock, Thread
from typing import Any


class MCPError(RuntimeError):
    pass


class MCPStdioClient:
    def __init__(
        self,
        *,
        name: str,
        command: str,
        arguments: tuple[str, ...] = (),
        cwd: Path,
        environment: dict[str, str] | None = None,
        timeout_seconds: float = 15,
    ) -> None:
        self.name = name
        self.command = command
        self.arguments = arguments
        self.cwd = cwd
        self.environment = dict(environment or {})
        self.timeout_seconds = timeout_seconds
        self._process: subprocess.Popen[str] | None = None
        self._responses: Queue[dict[str, Any] | BaseException] = Queue()
        self._request_lock = RLock()
        self._next_id = 0
        self.server_info: dict[str, Any] = {}

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        if self.running:
            return
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        environment = {**os.environ, **self.environment}
        try:
            self._process = subprocess.Popen(
                [self.command, *self.arguments],
                cwd=self.cwd,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
        except OSError as exc:
            raise MCPError(f"无法启动 MCP Server {self.name}：{exc}") from exc
        Thread(target=self._read_stdout, daemon=True, name=f"mcp-{self.name}-stdout").start()
        Thread(target=self._drain_stderr, daemon=True, name=f"mcp-{self.name}-stderr").start()
        initialized = self.request("initialize", {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "zhaoxi-mcp-client", "version": "1.0.0"},
        })
        self.server_info = dict(initialized.get("serverInfo") or {})
        self.notify("notifications/initialized")

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._request_lock:
            if not self.running and method != "initialize":
                self.start()
            process = self._process
            if process is None or process.stdin is None:
                raise MCPError(f"MCP Server {self.name} 未运行")
            self._next_id += 1
            request_id = self._next_id
            payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
            if params is not None:
                payload["params"] = params
            try:
                process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise MCPError(f"MCP Server {self.name} 连接已关闭") from exc
            while True:
                try:
                    response = self._responses.get(timeout=self.timeout_seconds)
                except Empty as exc:
                    raise MCPError(f"MCP Server {self.name} 响应超时") from exc
                if isinstance(response, BaseException):
                    raise MCPError(str(response)) from response
                if response.get("id") != request_id:
                    continue
                if error := response.get("error"):
                    message = error.get("message") if isinstance(error, dict) else str(error)
                    raise MCPError(f"MCP Server {self.name}：{message}")
                result = response.get("result")
                return result if isinstance(result, dict) else {}

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        process = self._process
        if process is None or process.stdin is None:
            return
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        process.stdin.flush()

    def list_tools(self) -> list[dict[str, Any]]:
        self.start()
        result = self.request("tools/list", {})
        tools = result.get("tools", [])
        if not isinstance(tools, list):
            raise MCPError(f"MCP Server {self.name} 返回了无效 tools/list")
        return [tool for tool in tools if isinstance(tool, dict)]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": arguments})

    def close(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict) and "id" in value:
                    self._responses.put(value)
        except BaseException as exc:
            self._responses.put(exc)

    def _drain_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for _line in process.stderr:
            pass
