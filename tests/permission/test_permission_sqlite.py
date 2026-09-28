from datetime import UTC, datetime, timedelta

import pytest

from zhaoxi.errors import ConfirmationExpiredError

from zhaoxi.permission.models import (
    InvocationOrigin,
    PendingConfirmation,
    PermissionLevel,
    PermissionRequest,
)
from zhaoxi.permission.sqlite import SQLitePermissionStore


def request():
    return PermissionRequest(
        request_id="request-1",
        tool_name="write.test",
        permission=PermissionLevel.WRITE,
        arguments={"private": "value"},
        arguments_digest="digest",
        resource_scope="test:item",
        action_summary="写测试",
        origin=InvocationOrigin.AGENT,
    )


def test_permission_pending_approval_and_consumption_survive_restart(tmp_path):
    path = tmp_path / "permission.db"
    store = SQLitePermissionStore(path)
    pending = PendingConfirmation(
        request=request(),
        question="允许吗",
        risk_summary="写入",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    store.save_pending(pending)

    restored = SQLitePermissionStore(path)
    grant = restored.approve(pending.confirmation_id)
    restored_again = SQLitePermissionStore(path)
    assert restored_again.consume_matching(pending.request).grant_id == grant.grant_id
    assert SQLitePermissionStore(path).consume_matching(pending.request) is None


def test_permission_denial_survives_restart(tmp_path):
    path = tmp_path / "permission.db"
    store = SQLitePermissionStore(path)
    pending = PendingConfirmation(
        request=request(),
        question="允许吗",
        risk_summary="写入",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    store.save_pending(pending)
    store.deny(pending.confirmation_id)
    assert SQLitePermissionStore(path).pending[pending.confirmation_id].approved is False


def test_expired_pending_can_be_closed_without_allowing_approval(tmp_path):
    path = tmp_path / "permission.db"
    store = SQLitePermissionStore(path)
    pending = PendingConfirmation(
        request=request(), question="允许吗", risk_summary="写入",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    store.save_pending(pending)

    with pytest.raises(ConfirmationExpiredError):
        store.approve(pending.confirmation_id)
    store.deny(pending.confirmation_id)

    restored = SQLitePermissionStore(path).pending[pending.confirmation_id]
    assert restored.resolved is True
    assert restored.approved is False
