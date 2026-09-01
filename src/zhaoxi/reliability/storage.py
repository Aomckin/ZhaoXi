"""Verified multi-database health, backup, retention, and restore operations."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from zhaoxi import __version__


@dataclass(frozen=True, slots=True)
class DataStoreSpec:
    name: str
    path: Path
    kind: str = "sqlite"
    sensitive: bool = True


class BackupError(RuntimeError):
    pass


class BackupManager:
    def __init__(
        self,
        backup_directory: str | Path,
        stores: list[DataStoreSpec],
        *,
        retention_count: int = 14,
    ) -> None:
        if retention_count < 1:
            raise ValueError("backup retention_count 必须至少为 1")
        names = [store.name for store in stores]
        if len(names) != len(set(names)):
            raise ValueError("data store name 必须唯一")
        self.backup_directory = Path(backup_directory).resolve()
        self.stores = stores
        self.retention_count = retention_count

    def health(self) -> dict[str, dict[str, object]]:
        result = {}
        for store in self.stores:
            path = store.path.resolve()
            item: dict[str, object] = {"kind": store.kind, "exists": path.exists(), "healthy": True}
            if path.exists() and store.kind == "sqlite":
                try:
                    with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as connection:
                        row = connection.execute("PRAGMA quick_check").fetchone()
                    item["healthy"] = bool(row and row[0] == "ok")
                except sqlite3.Error:
                    item["healthy"] = False
            result[store.name] = item
        return result

    def create(self) -> Path:
        self.backup_directory.mkdir(parents=True, exist_ok=True)
        backup_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid4().hex[:8]
        target = self.backup_directory / backup_id
        target.mkdir()
        files = []
        try:
            for store in self.stores:
                source = store.path.resolve()
                if not source.exists():
                    continue
                destination = target / f"{store.name}.db" if store.kind == "sqlite" else target / store.name
                if store.kind == "sqlite":
                    self._backup_sqlite(source, destination)
                    self._check_sqlite(destination)
                else:
                    shutil.copy2(source, destination)
                files.append({
                    "name": store.name,
                    "kind": store.kind,
                    "file": destination.name,
                    "size": destination.stat().st_size,
                    "sha256": self._sha256(destination),
                })
            manifest = {
                "format_version": 1,
                "backup_id": backup_id,
                "application_version": __version__,
                "created_at": datetime.now(UTC).isoformat(),
                "files": files,
            }
            # The manifest is the commit marker and is written only after every
            # payload has passed its integrity and checksum checks.
            (target / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self.verify(target)
            self._apply_retention()
            return target
        except Exception as exc:
            shutil.rmtree(target, ignore_errors=True)
            if isinstance(exc, BackupError):
                raise
            raise BackupError(f"备份失败：{type(exc).__name__}") from exc

    def verify(self, backup_path: str | Path) -> dict[str, object]:
        directory = self._validated_backup_path(backup_path)
        try:
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError) as exc:
            raise BackupError("备份 manifest 无效。") from exc
        if manifest.get("format_version") != 1 or manifest.get("backup_id") != directory.name:
            raise BackupError("备份 manifest 版本或 ID 不匹配。")
        known_names = {store.name for store in self.stores}
        for item in manifest.get("files", []):
            if item.get("name") not in known_names:
                raise BackupError("备份包含未知数据项。")
            path = directory / item["file"]
            if not path.is_file() or path.stat().st_size != item["size"]:
                raise BackupError(f"备份文件缺失或大小不符：{item.get('name')}")
            if self._sha256(path) != item["sha256"]:
                raise BackupError(f"备份校验和不符：{item.get('name')}")
            if item["kind"] == "sqlite":
                self._check_sqlite(path)
        return manifest

    def restore(self, backup_path: str | Path) -> Path:
        directory = self._validated_backup_path(backup_path)
        manifest = self.verify(directory)
        safeguard = self.create()
        stores = {store.name: store for store in self.stores}
        staged: list[tuple[Path, Path, str]] = []
        try:
            for item in manifest["files"]:
                target = stores[item["name"]].path.resolve()
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(f".{target.name}.{uuid4().hex}.restore")
                shutil.copy2(directory / item["file"], temporary)
                if item["kind"] == "sqlite":
                    self._check_sqlite(temporary)
                staged.append((temporary, target, item["kind"]))
            for temporary, target, kind in staged:
                if kind == "sqlite":
                    self._restore_sqlite(temporary, target)
                    temporary.unlink(missing_ok=True)
                else:
                    shutil.copy2(temporary, target)
                    temporary.unlink(missing_ok=True)
            return safeguard
        except Exception as exc:
            for temporary, _, _ in staged:
                temporary.unlink(missing_ok=True)
            raise BackupError(f"恢复失败，原数据未被替换：{type(exc).__name__}") from exc

    def inventory(self) -> list[dict[str, object]]:
        return [
            {**asdict(store), "path": str(store.path), "exists": store.path.exists()}
            for store in self.stores
        ]

    def _validated_backup_path(self, backup_path: str | Path) -> Path:
        directory = Path(backup_path).resolve()
        if directory.parent != self.backup_directory or not directory.is_dir():
            raise BackupError("备份路径不在配置的备份目录中。")
        return directory

    def _apply_retention(self) -> None:
        backups = sorted(
            (path for path in self.backup_directory.iterdir() if path.is_dir() and not path.name.startswith(".")),
            key=lambda path: path.name,
            reverse=True,
        )
        for old in backups[self.retention_count:]:
            shutil.rmtree(old)

    @staticmethod
    def _backup_sqlite(source: Path, destination: Path) -> None:
        with closing(sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)) as source_db:
            with closing(sqlite3.connect(destination)) as target_db:
                source_db.backup(target_db)

    @staticmethod
    def _restore_sqlite(source: Path, destination: Path) -> None:
        with closing(sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)) as source_db:
            with closing(sqlite3.connect(destination)) as target_db:
                source_db.backup(target_db)

    @staticmethod
    def _check_sqlite(path: Path) -> None:
        try:
            with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as connection:
                row = connection.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.Error as exc:
            raise BackupError(f"SQLite 文件无法读取：{path.name}") from exc
        if not row or row[0] != "ok":
            raise BackupError(f"SQLite 完整性检查失败：{path.name}")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
