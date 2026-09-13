from __future__ import annotations

import json
import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from zhaoxi.permission.models import PermissionLevel, SideEffect

from tools.job_application_tool.client import BrowserBridgeClient
from tools.job_application_tool.models import ApplySafeFieldsInput
from tools.job_application_tool.native_host import NativeHostBroker
from tools.job_application_tool.native_host.protocol import PROTOCOL_VERSION
from tools.job_application_tool.package import create_package
from tools.job_application_tool.tool import ApplySafeFieldsTool, create_tools


class FakeTransport:
    def __init__(self) -> None:
        self.messages = []

    async def request(self, message, timeout):
        self.messages.append((message, timeout))
        return {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": message["request_id"],
            "session_id": message["session_id"],
            "ok": True,
            "result": {"type": message["type"]},
            "error": None,
        }


def test_package_exposes_six_high_level_tools_and_no_submit_capability():
    package = create_package()
    client = BrowserBridgeClient(FakeTransport())
    names = [tool.name for tool in create_tools(client)]
    assert names == [
        "job_application_inspect_page",
        "job_application_build_plan",
        "job_application_apply_safe_fields",
        "job_application_get_review",
        "job_application_get_profile",
        "job_application_update_profile",
    ]
    assert all("submit" not in name and "declaration" not in name for name in names)
    assert package.package_id == "job-application-tool"
    assert package.capability_declaration().tool is True


def test_apply_tool_is_write_non_replayable_and_has_no_bypass_inputs():
    tool = ApplySafeFieldsTool(BrowserBridgeClient(FakeTransport()))
    assert tool.permission is PermissionLevel.WRITE
    assert tool.side_effects == frozenset({SideEffect.EXTERNAL_SERVICE_WRITE})
    assert tool.safe_to_replay({}) is False
    schema = tool.input_model.model_json_schema()
    assert set(schema["properties"]) == {
        "plan_id", "expected_page_fingerprint", "expected_profile_revision"
    }
    with pytest.raises(ValidationError):
        ApplySafeFieldsInput.model_validate({
            "plan_id": "jap_1234567890123456",
            "expected_page_fingerprint": "sha256:1234567890abcdef",
            "expected_profile_revision": 1,
            "force": True,
        })


def test_tool_sends_only_validated_high_level_request():
    transport = FakeTransport()
    tool = create_tools(BrowserBridgeClient(transport))[0]
    result = asyncio.run(tool.run({"include_options": False}))
    assert result.success is True
    message, _ = transport.messages[0]
    assert message["type"] == "inspect_page"
    assert message["payload"] == {"include_options": False}


def test_native_host_rejects_unknown_actions_and_fields():
    valid = {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": "request-123",
        "session_id": "current",
        "type": "inspect_page",
        "payload": {},
        "deadline_ms": 1000,
    }
    assert NativeHostBroker.validate_request(valid) == (True, "")
    assert NativeHostBroker.validate_request({**valid, "type": "submit"})[0] is False
    assert NativeHostBroker.validate_request({**valid, "javascript": "alert(1)"})[0] is False


def test_profile_schema_marks_declarations_and_family_manual_only():
    path = Path(__file__).parents[1] / "schema" / "profile.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    properties = schema["properties"]
    assert properties["declarations"]["x-zhaoxi-policy"] == "never_fill"
    assert properties["family_members"]["x-zhaoxi-policy"] == "manual_only"


def test_extension_contains_only_v01_page_and_control_adapters():
    extension = Path(__file__).parents[1] / "browser_extension"
    page_source = (extension / "adapters" / "page_adapters.js").read_text(encoding="utf-8")
    control_source = (extension / "adapters" / "control_adapters.js").read_text(encoding="utf-8")
    for adapter in ("generic-page", "moka-page", "beisen-page", "feishu-page"):
        assert adapter in page_source
    for adapter in ("native-control", "ant-design-control", "element-control"):
        assert adapter in control_source
    for forbidden in ("submit_after_fill", "ignore_policy", "fill_declarations"):
        assert forbidden not in (page_source + control_source)


def test_extension_manifest_is_minimal_and_has_no_site_wide_access():
    extension = Path(__file__).parents[1] / "browser_extension"
    manifest = json.loads((extension / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 3
    assert set(manifest["permissions"]) == {"activeTab", "nativeMessaging", "scripting", "storage"}
    assert "host_permissions" not in manifest
    assert "optional_host_permissions" not in manifest
    assert manifest["background"] == {"service_worker": "background.js"}
    assert manifest["action"]["default_popup"] == "popup.html"
