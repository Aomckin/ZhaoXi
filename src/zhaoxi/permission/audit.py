"""Append-only, redacted permission audit sinks."""

from pathlib import Path

from zhaoxi.errors import AuditWriteError
from zhaoxi.permission.models import AuditEvent


class InMemoryAuditSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def write(self, event: AuditEvent) -> None:
        self.events.append(event)


class JsonlAuditSink:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def write(self, event: AuditEvent) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(event.model_dump_json() + "\n")
        except OSError as exc:
            raise AuditWriteError("无法写入权限审计日志。") from exc

    def read(self, limit: int = 20) -> list[AuditEvent]:
        if not self.path.exists():
            return []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()[-limit:]
            return [AuditEvent.model_validate_json(line) for line in lines if line.strip()]
        except (OSError, ValueError) as exc:
            raise AuditWriteError("无法读取权限审计日志。") from exc
