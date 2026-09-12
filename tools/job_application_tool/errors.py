"""Errors that are safe to expose at the Tool boundary."""


class JobApplicationError(RuntimeError):
    def __init__(self, message: str, *, code: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class BrowserBridgeUnavailable(JobApplicationError):
    def __init__(self, message: str = "浏览器扩展尚未连接 Native Messaging Host。") -> None:
        super().__init__(message, code="browser_bridge_unavailable", retryable=True)
