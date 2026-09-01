"""Append-only, redacted permission audit sinks."""

from pathlib import Path
import shutil

from zhaoxi.errors import AuditWriteError
from zhaoxi.permission.models import AuditEvent


class InMemoryAuditSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def write(self, event: AuditEvent) -> None:
        self.events.append(event)


class JsonlAuditSink:
    def __init__(
        self,
        path: str | Path,
        *,
        max_bytes: int = 10 * 1024 * 1024,
        backup_count: int = 5,
    ) -> None:
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.backup_count = backup_count

    def write(self, event: AuditEvent) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed(len(event.model_dump_json().encode("utf-8")) + 1)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(event.model_dump_json() + "\n")
        except OSError as exc:
            raise AuditWriteError("无法写入权限审计日志。") from exc

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        if not self.path.exists() or self.path.stat().st_size + incoming_bytes <= self.max_bytes:
            return
        for index in range(self.backup_count, 1, -1):
            older = self.path.with_name(f"{self.path.name}.{index - 1}")
            newer = self.path.with_name(f"{self.path.name}.{index}")
            if older.exists():
                shutil.copy2(older, newer)
        shutil.copy2(self.path, self.path.with_name(f"{self.path.name}.1"))
        self.path.write_text("", encoding="utf-8")

    def read(self, limit: int = 20) -> list[AuditEvent]:
        if not self.path.exists():
            return []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()[-limit:]
            return [AuditEvent.model_validate_json(line) for line in lines if line.strip()]
        except (OSError, ValueError) as exc:
            raise AuditWriteError("无法读取权限审计日志。") from exc
