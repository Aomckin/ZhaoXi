"""Application exception hierarchy."""


class ZhaoxiError(Exception):
    """Base error for expected Zhaoxi failures."""


class ConfigError(ZhaoxiError):
    """Configuration is missing or invalid."""


class ProviderError(ZhaoxiError):
    """A model provider request failed."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "provider_error",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class ToolError(ZhaoxiError):
    """A tool failed."""


class ToolNotFoundError(ToolError):
    """A requested tool is not registered."""


class ToolValidationError(ToolError):
    """Tool arguments are invalid."""


class AgentLoopError(ZhaoxiError):
    """The agent loop could not produce a final response."""

    def __init__(self, message: str, *, code: str = "agent_loop_error") -> None:
        super().__init__(message)
        self.code = code


class SessionError(ZhaoxiError):
    """A session operation failed."""


class MemoryError(ZhaoxiError):
    """A long-term memory operation failed."""


class MemoryNotFoundError(MemoryError):
    """A requested memory record does not exist."""


class PlannerError(ZhaoxiError):
    """A planned task could not be processed."""


class PlanValidationError(PlannerError):
    """A model-produced plan is invalid."""


class InvalidStateTransitionError(PlannerError):
    """A planner entity attempted an invalid state transition."""


class PlannerLimitError(PlannerError):
    """A deterministic planner execution limit was reached."""


class PlannerTimeoutError(PlannerError):
    """A planned task exceeded its time limit."""


class PlannerTaskNotFoundError(PlannerError):
    """A requested planned task does not exist."""


class PlannerTaskCancelledError(PlannerError):
    """A planned task was cancelled."""


class PermissionError(ZhaoxiError):
    """A tool invocation could not pass the permission boundary."""


class PermissionDeniedError(PermissionError):
    """A permission policy or user denied an invocation."""


class ConfirmationRequiredError(PermissionError):
    """An invocation is waiting for explicit user confirmation."""


class ConfirmationExpiredError(PermissionError):
    """A pending confirmation has expired."""


class InvalidGrantError(PermissionError):
    """A grant does not match the invocation it was used for."""


class GrantRevokedError(PermissionError):
    """A revoked grant was used."""


class AuditWriteError(PermissionError):
    """A required permission audit event could not be persisted."""


class RollbackError(PermissionError):
    """A tool rollback hook failed."""
