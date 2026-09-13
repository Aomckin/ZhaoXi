"""Local deterministic permission policy."""

from zhaoxi.permission.models import (
    PermissionDecision,
    PermissionLevel,
    PermissionRequest,
    PermissionStatus,
)


class DefaultPermissionPolicy:
    def __init__(self, policies: dict[PermissionLevel, PermissionStatus] | None = None) -> None:
        self.policies = policies or {
            PermissionLevel.READ: PermissionStatus.ALLOW,
            PermissionLevel.WRITE: PermissionStatus.REQUIRE_CONFIRMATION,
            PermissionLevel.DELETE: PermissionStatus.REQUIRE_CONFIRMATION,
            PermissionLevel.EXTERNAL_ACTION: PermissionStatus.REQUIRE_CONFIRMATION,
            PermissionLevel.DANGEROUS: PermissionStatus.DENY,
        }

    def evaluate(self, request: PermissionRequest) -> PermissionDecision:
        memory_write = request.tool_name in {"remember_memory", "update_memory"} and request.permission == PermissionLevel.WRITE
        if memory_write and any(marker in request.user_intent for marker in (
            "不要记", "别记", "不用记", "不许记", "不要保存", "别保存", "不要更新记忆", "别更新记忆",
        )):
            return PermissionDecision(status=PermissionStatus.DENY, reason_code="memory_forbidden_intent")
        if self._is_read_only(request.user_intent) and request.permission != PermissionLevel.READ:
            return PermissionDecision(status=PermissionStatus.DENY, reason_code="read_only_intent")
        if memory_write:
            if self.policies.get(PermissionLevel.WRITE) == PermissionStatus.DENY:
                return PermissionDecision(status=PermissionStatus.DENY, reason_code="default_deny")
            return PermissionDecision(status=PermissionStatus.ALLOW, reason_code="memory_write_default_allow")
        if self._is_explicit_user_authorization(request):
            return PermissionDecision(status=PermissionStatus.ALLOW, reason_code="explicit_user_intent")
        status = self.policies.get(request.permission, PermissionStatus.DENY)
        return PermissionDecision(status=status, reason_code=f"default_{status.value}")

    @staticmethod
    def _is_read_only(value: str) -> bool:
        return any(marker in value for marker in ("只读", "不要修改", "别修改", "不修改", "不要忘"))

    @staticmethod
    def _is_explicit_user_authorization(request: PermissionRequest) -> bool:
        """Recognize only narrow, same-turn commands; never infer broad consent."""
        intent = request.user_intent
        if request.tool_name == "remember_memory":
            return any(marker in intent for marker in ("记住", "记一下", "帮我记"))
        if request.tool_name == "forget_memory":
            return any(marker in intent for marker in ("忘掉", "忘记", "不用记"))
        return False
