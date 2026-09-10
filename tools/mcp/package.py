"""Zhaoxi Tool Package exposing installed MCP servers through ToolProviders."""

from __future__ import annotations

from pathlib import Path

from zhaoxi.sdk import CapabilityDeclaration

from tools.mcp.provider import MCPToolProvider
from tools.mcp.servers import selected_server_specs


class MCPToolPackage:
    package_id = "mcp-tool"
    package_version = "1.0.0"
    requires_sdk = ">=1.1,<2"

    def capability_declaration(self) -> CapabilityDeclaration:
        return CapabilityDeclaration(tool=True)

    def create_tools(self, config: dict[str, object]):
        return []

    def create_tool_providers(self, config: dict[str, object]):
        root = Path(__file__).resolve().parent
        timeout = float(config.get("timeout_seconds", 15))
        return [
            MCPToolProvider(spec, timeout_seconds=timeout)
            for spec in selected_server_specs(root, config)
        ]

    def workflow_paths(self) -> list[Path]:
        return []

    def routing_hints(self) -> list[dict[str, object]]:
        return []

    def reflection_sources(self) -> list[object]:
        return []

    def capabilities(self) -> dict[str, object]:
        return {
            "id": self.package_id,
            "name": "MCP Tools",
            "description": "将本地 MCP Server 的每项能力作为独立 Tool 动态注册。",
        }

    def health_check(self, config: dict[str, object]) -> dict[str, object]:
        specs = selected_server_specs(Path(__file__).resolve().parent, config)
        return {"configured": True, "reachable": True, "healthy": bool(specs)}


def create_package() -> MCPToolPackage:
    return MCPToolPackage()
