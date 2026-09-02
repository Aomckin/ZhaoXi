"""Normalized LifeHUD-Tool failures."""


class LifeHudError(RuntimeError):
    def __init__(self, message: str, *, code: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class UnsupportedSchemaVersion(LifeHudError):
    def __init__(self, actual: object, expected: str) -> None:
        super().__init__(
            f"不支持 Life HUD Agent Context schemaVersion={actual!r}，当前仅支持 {expected}。",
            code="unsupported_schema_version",
        )
