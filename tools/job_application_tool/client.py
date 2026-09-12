"""Client for the local Native Messaging broker.

The Chrome extension owns the Native Messaging connection. The native host
exposes a same-user local IPC endpoint so Zhaoxi can submit a bounded request to
that already-connected extension. No HTTP server is used.
"""

from __future__ import annotations

import asyncio
import os
from multiprocessing.connection import Client
from typing import Any, Protocol
from uuid import uuid4

from tools.job_application_tool.errors import BrowserBridgeUnavailable, JobApplicationError


PROTOCOL = "zhaoxi.job-application.native"
PROTOCOL_VERSION = 1
DEFAULT_WINDOWS_PIPE = r"\\.\pipe\zhaoxi-job-application-v1"
DEFAULT_UNIX_SOCKET = "/tmp/zhaoxi-job-application-v1.sock"


class Transport(Protocol):
    async def request(self, message: dict[str, Any], timeout: float) -> dict[str, Any]: ...


class LocalBrokerTransport:
    def __init__(self, address: str | None = None) -> None:
        self.address = address or (
            DEFAULT_WINDOWS_PIPE if os.name == "nt" else DEFAULT_UNIX_SOCKET
        )
        self.family = "AF_PIPE" if os.name == "nt" else "AF_UNIX"

    async def request(self, message: dict[str, Any], timeout: float) -> dict[str, Any]:
        return await asyncio.wait_for(asyncio.to_thread(self._request_sync, message), timeout)

    def _request_sync(self, message: dict[str, Any]) -> dict[str, Any]:
        try:
            connection = Client(self.address, family=self.family)
        except (OSError, EOFError) as exc:
            raise BrowserBridgeUnavailable() from exc
        try:
            connection.send(message)
            response = connection.recv()
        except (OSError, EOFError) as exc:
            raise BrowserBridgeUnavailable("浏览器桥连接已中断，请确认扩展处于启用状态。") from exc
        finally:
            connection.close()
        if not isinstance(response, dict):
            raise JobApplicationError("浏览器桥返回了无效响应。", code="invalid_bridge_response")
        return response


class JobApplicationClient:
    def __init__(self, transport: Transport | None = None, *, timeout: float = 15.0) -> None:
        self.transport = transport or LocalBrokerTransport()
        self.timeout = timeout

    async def call(self, message_type: str, payload: dict[str, Any]) -> Any:
        request_id = f"jar_{uuid4().hex}"
        envelope = {
            "protocol": PROTOCOL,
            "version": PROTOCOL_VERSION,
            "request_id": request_id,
            "type": message_type,
            "payload": payload,
            "deadline_ms": int(self.timeout * 1000),
        }
        try:
            response = await self.transport.request(envelope, self.timeout)
        except TimeoutError as exc:
            raise JobApplicationError("浏览器操作超时。", code="browser_timeout", retryable=True) from exc
        if response.get("request_id") != request_id:
            raise JobApplicationError("浏览器桥响应与请求不匹配。", code="request_mismatch")
        if response.get("protocol") != PROTOCOL or response.get("version") != PROTOCOL_VERSION:
            raise JobApplicationError("浏览器桥协议版本不兼容。", code="protocol_mismatch")
        if not response.get("ok"):
            error = response.get("error") or "browser_request_failed"
            message = response.get("message") or "浏览器操作失败。"
            raise JobApplicationError(message, code=str(error), retryable=False)
        return response.get("data")
