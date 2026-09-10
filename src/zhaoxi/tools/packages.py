"""Generic discovery for independently versioned Tool packages."""

from __future__ import annotations

from importlib import import_module, metadata
from pathlib import Path
from typing import Protocol
import os
import re

from dotenv import dotenv_values

from zhaoxi.tools.base import Tool
from zhaoxi.sdk import SDK_VERSION, CapabilityDeclaration, ToolProviderProtocol


class ToolPackage(Protocol):
    package_id: str
    package_version: str
    requires_sdk: str

    def create_tools(self, config: dict[str, object]) -> list[Tool]: ...
    def workflow_paths(self) -> list[Path]: ...
    def routing_hints(self) -> list[dict[str, object]]: ...
    def capabilities(self) -> dict[str, object]: ...
    def reflection_sources(self) -> list[object]: ...
    def capability_declaration(self) -> CapabilityDeclaration: ...


def config_for_package(package_id: str) -> dict[str, object]:
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


def _as_bool(value: object, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value}")


def package_enabled(config: dict[str, object]) -> bool:
    # Presence on disk is discovery, not user consent to activate a capability.
    return _as_bool(config.get("enabled"), False)


_CAPABILITY_CONFIG_KEYS = {
    "tool": "tool_enabled",
    "workflow": "workflow_enabled",
    "router_hints": "router_hints_enabled",
    "proactive_provider": "proactive_enabled",
    "reflection_provider": "reflection_enabled",
    "state_signal_provider": "state_signals_enabled",
}


def declared_capabilities(package: ToolPackage) -> CapabilityDeclaration:
    factory = getattr(package, "capability_declaration", None)
    if factory is None:
        raise ValueError(f"Tool Package {package.package_id} lacks a capability declaration")
    return CapabilityDeclaration.model_validate(factory())


def capability_enabled(
    declaration: CapabilityDeclaration,
    name: str,
    config: dict[str, object],
) -> bool:
    if not getattr(declaration, name):
        return False
    return _as_bool(config.get(_CAPABILITY_CONFIG_KEYS[name]), True)


def sdk_compatible(requirement: str) -> bool:
    """Validate the supported public SDK major without another runtime dependency."""
    current_major = int(SDK_VERSION.split(".", 1)[0])
    lower = re.search(r">=\s*(\d+)", requirement)
    upper = re.search(r"<\s*(\d+)", requirement)
    return bool(lower) and int(lower.group(1)) <= current_major and (
        upper is None or current_major < int(upper.group(1))
    )


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


def create_package_tools(
    package: ToolPackage,
    config: dict[str, object] | None = None,
) -> list[Tool]:
    resolved = config if config is not None else config_for_package(package.package_id)
    return package.create_tools(resolved)


def create_package_tool_providers(
    package: ToolPackage,
    config: dict[str, object] | None = None,
) -> list[ToolProviderProtocol]:
    factory = getattr(package, "create_tool_providers", None)
    if factory is None:
        return []
    resolved = config if config is not None else config_for_package(package.package_id)
    return list(factory(resolved))
