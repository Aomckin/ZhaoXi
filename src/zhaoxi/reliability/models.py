"""Stable error contract shared across runtime boundaries."""

from __future__ import annotations

from enum import StrEnum

from zhaoxi.errors import ZhaoxiError


class ErrorCategory(StrEnum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    VALIDATION = "validation"
    PERMISSION = "permission"
    CORRUPTION = "corruption"


class ReliabilityError(ZhaoxiError):
    """Expected failure with explicit retry and replay semantics."""

    def __init__(
        self,
        user_message: str,
        *,
        code: str,
        category: ErrorCategory,
        retryable: bool = False,
        safe_to_replay: bool = False,
        trace_id: str | None = None,
        cause_type: str | None = None,
    ) -> None:
        if retryable and category not in {ErrorCategory.TRANSIENT}:
            raise ValueError("只有 transient 错误可以标记为 retryable")
        if safe_to_replay and not retryable:
            raise ValueError("safe_to_replay 仅适用于 retryable 错误")
        super().__init__(user_message)
        self.user_message = user_message
        self.code = code
        self.category = category
        self.retryable = retryable
        self.safe_to_replay = safe_to_replay
        self.trace_id = trace_id
        self.cause_type = cause_type

    def safe_summary(self) -> dict[str, str | bool | None]:
        return {
            "code": self.code,
            "category": self.category.value,
            "retryable": self.retryable,
            "safe_to_replay": self.safe_to_replay,
            "trace_id": self.trace_id,
            "cause_type": self.cause_type,
        }
