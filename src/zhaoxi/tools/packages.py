"""Generic discovery for independently versioned Tool packages."""

from __future__ import annotations

from importlib import import_module, metadata
from pathlib import Path
from typing import Protocol
import os

from dotenv import dotenv_values

from zhaoxi.tools.base import Tool


class ToolPackage(Protocol):
    package_id: str
    package_version: str

    def create_tools(self, config: dict[str, object]) -> list[Tool]: ...
    def workflow_paths(self) -> list[Path]: ...
    def routing_hints(self) -> list[dict[str, object]]: ...
    def capabilities(self) -> dict[str, object]: ...
    def reflection_sources(self) -> list[object]: ...


def _config_for(package_id: str) -> dict[str, object]:
    identifier = package_id.removesuffix("-tool").replace("-", "_").upper()
    prefix = f"ZHAOXI_TOOL_{identifier}_"
    values = {**dotenv_values(".env"), **os.environ}
    config = {
        key[len(prefix):].lower(): value
        for key, value in values.items()
        if key.startswith(prefix) and value is not None
    }
    # One-release compatibility is owned by the package boundary, not Settings.
    legacy_prefix = f"ZHAOXI_{identifier}_"
    for key, value in values.items():
        if key.startswith(legacy_prefix) and value is not None:
            config.setdefault(key[len(legacy_prefix):].lower(), value)
    return config


def discover_tool_packages(
    local_root: str | Path = "tools",
    *,
    errors: list[dict[str, str]] | None = None,
) -> list[ToolPackage]:
    packages: dict[str, ToolPackage] = {}
    entry_points = metadata.entry_points(group="zhaoxi.tools")
    for entry_point in entry_points:
        try:
            package = entry_point.load()()
            packages[package.package_id] = package
        except Exception as exc:
            if errors is not None:
                errors.append({"source": entry_point.name, "error": type(exc).__name__})

    root = Path(local_root)
    if root.exists():
        for child in sorted(root.iterdir()):
            if child.is_dir() and (child / "package.py").exists():
                try:
                    module = import_module(f"tools.{child.name}.package")
                    package = module.create_package()
                    packages.setdefault(package.package_id, package)
                except Exception as exc:
                    if errors is not None:
                        errors.append({"source": child.name, "error": type(exc).__name__})
    return list(packages.values())


def create_package_tools(package: ToolPackage) -> list[Tool]:
    return package.create_tools(_config_for(package.package_id))
