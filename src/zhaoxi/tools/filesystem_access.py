"""Persistent read/write boundaries for the local Filesystem MCP."""

from __future__ import annotations

import json
from pathlib import Path


def default_filesystem_access() -> dict[str, list[str]]:
    sandbox = str(Path("tools/mcp/data/filesystem").resolve())
    return {"read_directories": [sandbox], "write_directories": [sandbox]}


def load_filesystem_access(path: Path) -> dict[str, list[str]]:
    defaults = default_filesystem_access()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        legacy = payload.get("directories")
        read = payload.get("read_directories", legacy)
        write = payload.get("write_directories", legacy)
        if (
            isinstance(read, list)
            and read
            and all(isinstance(item, str) for item in read)
            and isinstance(write, list)
            and write
            and all(isinstance(item, str) for item in write)
        ):
            return {"read_directories": read, "write_directories": write}
    except (OSError, ValueError, TypeError):
        pass
    return defaults


def resolve_access_directories(values: list[str]) -> list[str]:
    resolved: list[str] = []
    for value in values:
        raw = value.strip()
        if not raw or len(raw) > 1024:
            raise ValueError("目录不能为空，且单个路径不能超过 1024 个字符。")
        path = Path(raw).expanduser()
        if not path.is_absolute():
            raise ValueError(f"请输入绝对路径：{raw}")
        try:
            path = path.resolve(strict=True)
        except OSError as exc:
            raise ValueError(f"目录不存在或无法访问：{raw}") from exc
        if not path.is_dir():
            raise ValueError(f"路径不是目录：{raw}")
        normalized = str(path)
        if normalized not in resolved:
            resolved.append(normalized)
    return resolved


def validate_write_subset(read_directories: list[str], write_directories: list[str]) -> None:
    read_roots = tuple(Path(item) for item in read_directories)
    for raw in write_directories:
        write_root = Path(raw)
        if not any(write_root == root or root in write_root.parents for root in read_roots):
            raise ValueError(f"可修改目录必须位于某个可读取目录内：{raw}")


def save_filesystem_access(
    path: Path,
    *,
    read_directories: list[str],
    write_directories: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {
                "read_directories": read_directories,
                "write_directories": write_directories,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    temporary.replace(path)


def filesystem_server_directories(access: dict[str, list[str]]) -> tuple[str, ...]:
    """The MCP sees the union; Core separately blocks writes outside write roots."""
    return tuple(dict.fromkeys(access["read_directories"] + access["write_directories"]))
