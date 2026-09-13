"""Strict versioned protocol shared by the Python bridge and native host."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


PROTOCOL_VERSION = 1
HOST_VERSION = "0.1.0"
MAX_NATIVE_MESSAGE_BYTES = 1024 * 1024
DEFAULT_WINDOWS_PIPE = r"\\.\pipe\zhaoxi-job-application-v1"
DEFAULT_UNIX_SOCKET = "/tmp/zhaoxi-job-application-v1.sock"

RequestType = Literal[
    "bridge_status",
    "inspect_page",
    "build_plan",
    "apply_safe_fields",
    "get_review",
    "get_profile",
    "update_profile",
    "end_session",
    "clear_expired_plans",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RequestEnvelope(StrictModel):
    protocol_version: Literal[1] = PROTOCOL_VERSION
    request_id: str = Field(min_length=8, max_length=160)
    session_id: str = Field(min_length=1, max_length=160)
    type: RequestType
    payload: dict[str, Any] = Field(default_factory=dict)
    deadline_ms: int = Field(default=15_000, ge=100, le=120_000)


class ErrorPayload(StrictModel):
    code: str
    message: str
    retryable: bool = False


class ResponseEnvelope(StrictModel):
    protocol_version: Literal[1] = PROTOCOL_VERSION
    request_id: str
    session_id: str
    ok: bool
    result: Any = None
    error: ErrorPayload | None = None


ERROR_RETRYABLE = {
    "browser_bridge_unavailable": True,
    "extension_not_connected": True,
    "content_script_unavailable": True,
    "timeout": True,
    "host_crashed": True,
}


def error_response(request_id: str, session_id: str, code: str, message: str) -> dict[str, Any]:
    return ResponseEnvelope(
        request_id=request_id,
        session_id=session_id,
        ok=False,
        error=ErrorPayload(code=code, message=message, retryable=ERROR_RETRYABLE.get(code, False)),
    ).model_dump()
