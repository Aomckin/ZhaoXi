from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path

import pytest
from pydantic import ValidationError

from tools.job_application_tool.client import BrowserBridgeClient, LocalBrokerTransport
from tools.job_application_tool.errors import BrowserBridgeUnavailable, JobApplicationError
from tools.job_application_tool.models import InspectPageInput
from tools.job_application_tool.native_host.host import NativeHostBroker
from tools.job_application_tool.native_host.install_host import manifest_payload, validate_extension_id
from tools.job_application_tool.native_host.protocol import (
    PROTOCOL_VERSION,
    RequestEnvelope,
    ResponseEnvelope,
    error_response,
)


def test_native_message_framing_round_trip():
    message = RequestEnvelope(
        request_id="req_12345678", session_id="current", type="inspect_page", payload={}
    ).model_dump()
    framed = NativeHostBroker.encode_framed(message)
    assert NativeHostBroker.read_framed(BytesIO(framed)) == message


def test_malformed_or_oversized_frames_are_rejected():
    with pytest.raises(ValueError, match="header"):
        NativeHostBroker.read_framed(BytesIO(b"\x01\x00"))
    with pytest.raises(ValueError, match="too large"):
        NativeHostBroker.read_framed(BytesIO((2 * 1024 * 1024).to_bytes(4, "little")))


def test_protocol_rejects_unknown_type_version_and_privileged_fields():
    base = {
        "protocol_version": 1,
        "request_id": "req_12345678",
        "session_id": "current",
        "type": "inspect_page",
        "payload": {},
        "deadline_ms": 1000,
    }
    for invalid in (
        {**base, "type": "submit"},
        {**base, "protocol_version": 2},
        {**base, "javascript": "alert(1)"},
    ):
        with pytest.raises(ValidationError):
            RequestEnvelope.model_validate(invalid)
    with pytest.raises(ValidationError):
        InspectPageInput.model_validate({"tab_id": 42})


def test_error_response_is_structured_and_strict():
    response = ResponseEnvelope.model_validate(
        error_response("req_12345678", "current", "extension_not_connected", "not connected")
    )
    assert response.ok is False
    assert response.error is not None
    assert response.error.retryable is True


def test_extension_id_validation_rejects_wildcards():
    assert validate_extension_id("a" * 32) == "a" * 32
    for invalid in ("*", "chrome-extension://abc/", "z" * 32, "a" * 31):
        with pytest.raises(ValueError):
            validate_extension_id(invalid)


def test_native_manifest_has_one_exact_origin_and_absolute_launcher(tmp_path):
    launcher = tmp_path / "host.cmd"
    payload = manifest_payload("b" * 32, launcher)
    assert payload["allowed_origins"] == [f"chrome-extension://{'b' * 32}/"]
    assert Path(payload["path"]).is_absolute()


def test_missing_native_host_maps_to_bridge_unavailable(monkeypatch):
    def fail_client(*_args, **_kwargs):
        raise FileNotFoundError("pipe missing")

    monkeypatch.setattr("tools.job_application_tool.client.browser_bridge.Client", fail_client)
    transport = LocalBrokerTransport(r"\\.\pipe\definitely-missing-zhaoxi-test")
    with pytest.raises(BrowserBridgeUnavailable):
        transport._request_sync({})


class ErrorTransport:
    async def request(self, message, timeout):
        return error_response(message["request_id"], message["session_id"], "permission_denied", "denied")


def test_client_preserves_structured_browser_error():
    client = BrowserBridgeClient(ErrorTransport())
    with pytest.raises(JobApplicationError) as captured:
        asyncio.run(client.call("inspect_page", {}))
    assert captured.value.code == "permission_denied"
    assert captured.value.retryable is False


class SlowTransport:
    async def request(self, message, timeout):
        await asyncio.sleep(0.05)
        return {}


def test_client_times_out_hung_host():
    client = BrowserBridgeClient(SlowTransport(), timeout=0.01)
    with pytest.raises(JobApplicationError) as captured:
        asyncio.run(client.call("inspect_page", {}))
    assert captured.value.code == "timeout"
    assert captured.value.retryable is True


class MismatchedTransport:
    async def request(self, message, timeout):
        return {"protocol_version": 2, "request_id": message["request_id"], "session_id": "current", "ok": True, "result": {}, "error": None}


def test_client_rejects_protocol_version_mismatch():
    client = BrowserBridgeClient(MismatchedTransport())
    with pytest.raises(JobApplicationError) as captured:
        asyncio.run(client.call("inspect_page", {}))
    assert captured.value.code == "protocol_mismatch"
