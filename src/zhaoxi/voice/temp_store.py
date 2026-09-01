"""Scoped temporary audio paths and conservative orphan cleanup."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path


class VoiceTempStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def create_wav_path(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        descriptor, raw_path = tempfile.mkstemp(prefix="capture-", suffix=".wav", dir=self.root)
        os.close(descriptor)
        return Path(raw_path)

    def remove(self, path: str | Path) -> None:
        target = Path(path).resolve()
        if target.parent != self.root:
            raise ValueError("拒绝删除 Voice 临时目录之外的文件")
        target.unlink(missing_ok=True)

    def cleanup_orphans(self, *, older_than_seconds: float = 86_400, now: float | None = None) -> int:
        if not self.root.exists():
            return 0
        threshold = (time.time() if now is None else now) - older_than_seconds
        removed = 0
        for path in self.root.glob("capture-*.wav"):
            if path.is_file() and path.stat().st_mtime < threshold:
                self.remove(path)
                removed += 1
        return removed

