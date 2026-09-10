"""Public structural protocols implemented by Tool packages."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from zhaoxi.sdk.capabilities import CapabilityDeclaration
from zhaoxi.sdk.signals import StateSignal


class ToolProtocol(Protocol):
    name: str
    description: str


class ToolProviderProtocol(Protocol):
    """Protocol-neutral source of Tools that may change at runtime."""

    provider_id: str

    def provide_tools(self) -> list[ToolProtocol]: ...
    def close(self) -> None: ...


class StateSignalProvider(Protocol):
    async def collect_signals(self, now: datetime) -> list[StateSignal]: ...


class ProactiveProvider(Protocol):
    async def collect(self, now: datetime) -> list[Any]: ...


class ReflectionProvider(Protocol):
    name: str
    async def collect(self, period: Any) -> Any: ...


class HealthCheckProtocol(Protocol):
    def health_check(self, config: dict[str, object]) -> dict[str, object]: ...


class ToolPackageProtocol(Protocol):
    package_id: str
    package_version: str
    requires_sdk: str

    def capability_declaration(self) -> CapabilityDeclaration: ...
    def create_tools(self, config: dict[str, object]) -> list[ToolProtocol]: ...
    def create_tool_providers(
        self, config: dict[str, object]
    ) -> list[ToolProviderProtocol]: ...
    def workflow_paths(self) -> list[Path]: ...
    def routing_hints(self) -> list[dict[str, object]]: ...
