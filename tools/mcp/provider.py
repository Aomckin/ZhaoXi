"""MCP implementation of the protocol-neutral Zhaoxi ToolProvider contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tools.mcp.adapter import MCPTool
from tools.mcp.client import MCPStdioClient


@dataclass(frozen=True, slots=True)
class MCPServerSpec:
    server_id: str
    command: str
    arguments: tuple[str, ...] = ()
    cwd: Path = Path(".")
    environment: dict[str, str] = field(default_factory=dict)


class MCPToolProvider:
    def __init__(self, spec: MCPServerSpec, *, timeout_seconds: float = 15) -> None:
        self.spec = spec
        self.provider_id = f"mcp:{spec.server_id}"
        self.client = MCPStdioClient(
            name=spec.server_id,
            command=spec.command,
            arguments=spec.arguments,
            cwd=spec.cwd,
            environment=spec.environment,
            timeout_seconds=timeout_seconds,
        )

    def provide_tools(self) -> list[MCPTool]:
        return [MCPTool(self.client, self.spec.server_id, item) for item in self.client.list_tools()]

    def close(self) -> None:
        self.client.close()
