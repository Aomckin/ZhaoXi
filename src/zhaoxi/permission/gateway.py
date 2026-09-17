"""Permission decision, confirmation, grant, and audit orchestration."""

from datetime import UTC, datetime, timedelta

from zhaoxi.permission.audit import InMemoryAuditSink
from zhaoxi.permission.models import (
    AuditEvent,
    PendingConfirmation,
    PermissionDecision,
    PermissionRequest,
    PermissionGrant,
    PermissionStatus,
)
from zhaoxi.errors import InvalidGrantError
from zhaoxi.permission.policy import DefaultPermissionPolicy
from zhaoxi.permission.store import InMemoryPermissionStore


class PermissionGateway:
    def __init__(
        self,
        *,
        policy: DefaultPermissionPolicy | None = None,
        store: InMemoryPermissionStore | None = None,
        audit=None,
        confirmation_ttl_seconds: float = 300,
    ) -> None:
        self.policy = policy or DefaultPermissionPolicy()
        self.store = store or InMemoryPermissionStore()
        self.audit = audit or InMemoryAuditSink()
        self.confirmation_ttl_seconds = confirmation_ttl_seconds

    def evaluate(
        self,
        request: PermissionRequest,
        *,
        confirm_write: bool | None = None,
    ) -> tuple[PermissionDecision, PendingConfirmation | None]:
        self._audit(request, "permission_requested")
        if self.store.consume_matching(request):
            decision = PermissionDecision(status=PermissionStatus.ALLOW, reason_code="approved_once")
            self._audit(request, "policy_allowed", reason_code=decision.reason_code)
            return decision, None
        decision = self.policy.evaluate(request)
        if request.permission.value == "write" and decision.status != PermissionStatus.DENY:
            if confirm_write is True:
                decision = PermissionDecision(
                    status=PermissionStatus.REQUIRE_CONFIRMATION,
                    reason_code="tool_write_confirmation_required",
                )
            elif confirm_write is False:
                decision = PermissionDecision(
                    status=PermissionStatus.ALLOW,
                    reason_code="tool_write_confirmation_disabled",
                )
        if decision.status == PermissionStatus.ALLOW:
            self._audit(request, "policy_allowed", reason_code=decision.reason_code)
            return decision, None
        if decision.status == PermissionStatus.DENY:
            self._audit(request, "permission_denied", reason_code=decision.reason_code)
            return decision, None
        pending = PendingConfirmation(
            request=request,
            question=f"是否允许朝汐执行：{request.action_summary}？",
            risk_summary=f"该操作需要 {request.permission.value} 权限，作用范围：{request.resource_scope}。",
            expires_at=datetime.now(UTC) + timedelta(seconds=self.confirmation_ttl_seconds),
        )
        self.store.save_pending(pending)
        self._audit(request, "confirmation_required", reason_code=decision.reason_code)
        return decision, pending

    def approve(self, confirmation_id: str):
        grant = self.store.approve(confirmation_id)
        request = self.store.pending[confirmation_id].request
        self._audit(request, "permission_approved", reason_code="user_approved_once")
        return grant

    def deny(self, confirmation_id: str):
        pending = self.store.deny(confirmation_id)
        self._audit(pending.request, "permission_denied", reason_code="user_denied")
        return pending

    def revoke(self, grant_id: str):
        grant = self.store.revoke(grant_id)
        request = self.store.pending[grant.confirmation_id].request
        self._audit(request, "grant_revoked", reason_code="user_revoked")
        return grant

    def grant_batch_member(
        self, confirmation_id: str, request: PermissionRequest
    ) -> PermissionGrant:
        """Derive a one-use grant for an immutable member of an approved batch."""
        pending = self.store.require_pending(confirmation_id)
        original = pending.request
        if not pending.resolved or pending.approved is not True:
            raise InvalidGrantError("批量权限确认尚未批准。")
        if (
            request.tool_name != original.tool_name
            or request.permission != original.permission
            or request.origin != original.origin
            or request.goal_id != original.goal_id
        ):
            raise InvalidGrantError("该调用不属于已批准的同类权限批次。")
        grant = PermissionGrant(
            confirmation_id=confirmation_id,
            invocation_id=request.invocation_id,
            tool_name=request.tool_name,
            arguments_digest=request.arguments_digest,
            resource_scope=request.resource_scope,
            expires_at=pending.expires_at,
        )
        self.store.save_grant(grant)
        return grant

    def record_execution(self, request: PermissionRequest, event_type: str, status: str) -> None:
        self._audit(request, event_type, result_status=status)

    def _audit(
        self,
        request: PermissionRequest,
        event_type: str,
        *,
        reason_code: str | None = None,
        result_status: str | None = None,
    ) -> None:
        self.audit.write(AuditEvent(
            event_type=event_type,
            invocation_id=request.invocation_id,
            request_id=request.request_id,
            tool_name=request.tool_name,
            permission=request.permission,
            origin=request.origin,
            goal_id=request.goal_id,
            step_id=request.step_id,
            reason_code=reason_code,
            arguments_digest=request.arguments_digest,
            resource_scope=request.resource_scope,
            result_status=result_status,
        ))
