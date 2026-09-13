"""Python client for the Native Messaging bridge.

The browser extension owns the Native Messaging connection. The native host
relays requests through a same-user AF_PIPE/AF_UNIX endpoint; no HTTP service is
opened and no browser data is cached here.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from multiprocessing.connection import Client
from typing import Any, Protocol
from uuid import uuid4

from pydantic import ValidationError

from tools.job_application_tool.errors import BrowserBridgeUnavailable, JobApplicationError
from tools.job_application_tool.native_host.protocol import (
    DEFAULT_UNIX_SOCKET,
    DEFAULT_WINDOWS_PIPE,
    PROTOCOL_VERSION,
    RequestEnvelope,
    ResponseEnvelope,
)


class Transport(Protocol):
    async def request(self, message: dict[str, Any], timeout: float) -> dict[str, Any]: ...


class LocalBrokerTransport:
    def __init__(self, address: str | None = None) -> None:
        self.address = address or (DEFAULT_WINDOWS_PIPE if os.name == "nt" else DEFAULT_UNIX_SOCKET)
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
            raise BrowserBridgeUnavailable("浏览器桥连接已中断，请确认扩展和 Native Host 已启用。") from exc
        finally:
            connection.close()
        if not isinstance(response, dict):
            raise JobApplicationError("浏览器桥返回了无效响应。", code="protocol_mismatch")
        return response


class BrowserBridgeClient:
    def __init__(self, transport: Transport | None = None, *, timeout: float = 15.0) -> None:
        self.transport = transport or LocalBrokerTransport()
        self.timeout = timeout
        self.reachable: bool | None = None
        self.last_error: str | None = None
        self.last_success_at: str | None = None
        self.active_session: str | None = None

    async def call(self, message_type: str, payload: dict[str, Any], *, session_id: str = "current") -> Any:
        request = RequestEnvelope(
            request_id=f"req_{uuid4().hex}",
            session_id=session_id,
            type=message_type,
            payload=payload,
            deadline_ms=max(100, int(self.timeout * 1000)),
        )
        try:
            raw = await asyncio.wait_for(
                self.transport.request(request.model_dump(), self.timeout),
                timeout=self.timeout,
            )
        except TimeoutError as exc:
            self.reachable = False
            self.last_error = "timeout"
            raise JobApplicationError("浏览器操作超时。", code="timeout", retryable=True) from exc
        except BrowserBridgeUnavailable:
            self.reachable = False
            self.last_error = "browser_bridge_unavailable"
            raise
        try:
            response = ResponseEnvelope.model_validate(raw)
        except ValidationError as exc:
            raise JobApplicationError("浏览器桥协议响应无效。", code="protocol_mismatch") from exc
        if response.request_id != request.request_id:
            raise JobApplicationError("浏览器桥响应与请求不匹配。", code="protocol_mismatch")
        if not response.ok:
            error = response.error
            self.reachable = True
            self.last_error = error.code if error else "browser_request_failed"
            raise JobApplicationError(
                error.message if error else "浏览器操作失败。",
                code=error.code if error else "browser_request_failed",
                retryable=error.retryable if error else False,
            )
        self.reachable = True
        self.last_error = None
        self.last_success_at = datetime.now(UTC).isoformat()
        if isinstance(response.result, dict):
            self.active_session = response.result.get("session_id", self.active_session)
        return response.result


JobApplicationClient = BrowserBridgeClient
