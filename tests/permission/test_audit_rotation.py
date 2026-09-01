from zhaoxi.permission.audit import JsonlAuditSink
from zhaoxi.permission.models import AuditEvent, InvocationOrigin, PermissionLevel


def event(index):
    return AuditEvent(
        event_type="permission_requested",
        invocation_id=f"inv-{index}",
        request_id=f"req-{index}",
        tool_name="test",
        permission=PermissionLevel.READ,
        origin=InvocationOrigin.AGENT,
        arguments_digest="digest",
        resource_scope="test",
    )


def test_jsonl_audit_rotates_without_losing_current_writer(tmp_path):
    path = tmp_path / "audit.jsonl"
    sink = JsonlAuditSink(path, max_bytes=1024, backup_count=2)
    for index in range(20):
        sink.write(event(index))

    assert path.exists()
    assert path.with_name("audit.jsonl.1").exists()
    assert sink.read(20)
