"""Tool registration and discovery."""

from __future__ import annotations

from typing import Any

from zhaoxi.errors import ToolNotFoundError, ToolValidationError
from zhaoxi.tools.base import Tool


class ToolRegistry:
    """Name-indexed collection used by the agent runtime."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ToolValidationError(f"工具已注册：{tool.name}")
        self._tools[tool.name] = tool
        return tool

    def unregister(self, name: str) -> Tool:
        try:
            return self._tools.pop(name)
        except KeyError as exc:
            raise ToolNotFoundError(f"工具不存在：{name}") from exc

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"工具不存在：{name}") from exc

    def list(self) -> list[Tool]:
        return list(self._tools.values())

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]
