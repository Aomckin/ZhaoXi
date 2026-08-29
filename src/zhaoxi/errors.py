"""Application exception hierarchy."""


class ZhaoxiError(Exception):
    """Base error for expected Zhaoxi failures."""


class ConfigError(ZhaoxiError):
    """Configuration is missing or invalid."""


class ProviderError(ZhaoxiError):
    """A model provider request failed."""


class ToolError(ZhaoxiError):
    """A tool failed."""


class ToolNotFoundError(ToolError):
    """A requested tool is not registered."""


class ToolValidationError(ToolError):
    """Tool arguments are invalid."""


class AgentLoopError(ZhaoxiError):
    """The agent loop could not produce a final response."""


class SessionError(ZhaoxiError):
    """A session operation failed."""


class MemoryError(ZhaoxiError):
    """A long-term memory operation failed."""


class MemoryNotFoundError(MemoryError):
    """A requested memory record does not exist."""
