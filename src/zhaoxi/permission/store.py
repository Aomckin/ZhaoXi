"""In-memory pending-confirmation and grant storage."""

from datetime import UTC, datetime

from zhaoxi.errors import ConfirmationExpiredError, InvalidGrantError
from zhaoxi.permission.models import PendingConfirmation, PermissionGrant, PermissionRequest


class InMemoryPermissionStore:
    def __init__(self) -> None:
        self.pending: dict[str, PendingConfirmation] = {}
        self.grants: dict[str, PermissionGrant] = {}

    def save_pending(self, item: PendingConfirmation) -> PendingConfirmation:
        self.pending[item.confirmation_id] = item
        return item

    def require_pending(self, confirmation_id: str) -> PendingConfirmation:
        try:
            item = self.pending[confirmation_id]
        except KeyError as exc:
            raise InvalidGrantError("没有找到该权限确认。") from exc
        if datetime.now(UTC) >= item.expires_at:
            raise ConfirmationExpiredError("权限确认已过期。")
        return item

    def approve(self, confirmation_id: str) -> PermissionGrant:
        item = self.require_pending(confirmation_id)
        if item.resolved:
            existing = next((g for g in self.grants.values() if g.confirmation_id == confirmation_id), None)
            if item.approved and existing:
                return existing
            raise InvalidGrantError("该权限确认已经处理。")
        item.resolved = True
        item.approved = True
        request = item.request
        grant = PermissionGrant(
            confirmation_id=confirmation_id,
            invocation_id=request.invocation_id,
            tool_name=request.tool_name,
            arguments_digest=request.arguments_digest,
            resource_scope=request.resource_scope,
            expires_at=item.expires_at,
        )
        self.grants[grant.grant_id] = grant
        return grant

    def deny(self, confirmation_id: str) -> PendingConfirmation:
        item = self.require_pending(confirmation_id)
        if not item.resolved:
            item.resolved = True
            item.approved = False
        return item

    def consume_matching(self, request: PermissionRequest) -> PermissionGrant | None:
        for grant in self.grants.values():
            if (
                not grant.revoked
                and grant.uses < grant.max_uses
                and datetime.now(UTC) < grant.expires_at
                and grant.invocation_id == request.invocation_id
                and grant.tool_name == request.tool_name
                and grant.arguments_digest == request.arguments_digest
                and grant.resource_scope == request.resource_scope
            ):
                grant.uses += 1
                return grant
        return None

    def revoke(self, grant_id: str) -> PermissionGrant:
        try:
            grant = self.grants[grant_id]
        except KeyError as exc:
            raise InvalidGrantError("没有找到该授权。") from exc
        grant.revoked = True
        return grant
