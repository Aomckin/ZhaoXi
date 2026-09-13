"""Tool registration and discovery."""

from __future__ import annotations

from typing import Any

from zhaoxi.errors import ToolNotFoundError, ToolValidationError
from zhaoxi.tools.base import Tool
from zhaoxi.permission.models import PermissionLevel, SideEffect
from zhaoxi.sdk.protocols import ToolProviderProtocol
from zhaoxi.tools.manifest import ToolControl, tool_metadata


class ToolRegistry:
    """Name-indexed collection used by the agent runtime."""

    def __init__(self, override_path=None) -> None:
        self._tools: dict[str, Tool] = {}
        self._providers: dict[str, ToolProviderProtocol] = {}
        self._provider_tools: dict[str, set[str]] = {}
        self.control = ToolControl(override_path)
        self.exposed_names: set[str] = set()

    def manifest(self, exposed=None) -> list[dict]:
        visible = self.exposed_names if exposed is None else set(exposed)
        sources = {name: provider for provider, names in self._provider_tools.items() for name in names}
        return [tool_metadata(tool, sources.get(tool.name, getattr(tool, "source", "builtin")),
                              self.control.overrides.get(tool.name, {}), visible) for tool in self.list()]

    def usable(self, name: str) -> bool:
        return any(item["name"] == name and item["enabled"] and item["available"] for item in self.manifest())

    def update_tools(self, *, name=None, group=None, enabled=None, force_expose=None, reset=False):
        if name is not None:
            self.get(name)
            names = [name]
        elif group is not None:
            names = [t["name"] for t in self.manifest() if t["group"] == group]
            if not names:
                raise ToolNotFoundError("钥匙组不存在")
        else:
            names = set(self._tools) | set(self.control.overrides)
        self.control.update(names, enabled=enabled, force_expose=force_expose, reset=reset)

    @staticmethod
    def _validate(tool: Tool) -> None:
        if not tool.name:
            raise ToolValidationError("工具名称不能为空")
        if not isinstance(tool.permission, PermissionLevel):
            raise ToolValidationError(f"工具 {tool.name} 缺少有效权限声明")
        if tool.__class__.permission_for is Tool.permission_for and tool.permission == PermissionLevel.READ and tool.side_effects != frozenset({SideEffect.NONE}):
            raise ToolValidationError(f"READ 工具 {tool.name} 不能声明副作用")
        if tool.__class__.permission_for is Tool.permission_for and tool.permission != PermissionLevel.READ and tool.side_effects == frozenset({SideEffect.NONE}):
            raise ToolValidationError(f"非 READ 工具 {tool.name} 必须声明副作用")

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ToolValidationError(f"工具已注册：{tool.name}")
        self._validate(tool)
        self._tools[tool.name] = tool
        return tool

    def register_provider(self, provider: ToolProviderProtocol) -> list[Tool]:
        """Discover and atomically register ordinary Tools from one provider."""
        if provider.provider_id in self._providers:
            raise ToolValidationError(f"ToolProvider 已注册：{provider.provider_id}")
        tools = list(provider.provide_tools())
        self._validate_provider_tools(provider.provider_id, tools, ignored_names=set())
        for tool in tools:
            self._tools[tool.name] = tool
        self._providers[provider.provider_id] = provider
        self._provider_tools[provider.provider_id] = {tool.name for tool in tools}
        return tools

    def refresh_provider(self, provider_id: str) -> list[Tool]:
        """Replace one provider's Tools without exposing a partially refreshed set."""
        try:
            provider = self._providers[provider_id]
        except KeyError as exc:
            raise ToolValidationError(f"ToolProvider 不存在：{provider_id}") from exc
        old_names = self._provider_tools[provider_id]
        tools = list(provider.provide_tools())
        self._validate_provider_tools(provider_id, tools, ignored_names=old_names)
        for name in old_names:
            self._tools.pop(name, None)
        for tool in tools:
            self._tools[tool.name] = tool
        self._provider_tools[provider_id] = {tool.name for tool in tools}
        return tools

    def unregister_provider(self, provider_id: str, *, close: bool = True) -> list[Tool]:
        try:
            provider = self._providers.pop(provider_id)
            names = self._provider_tools.pop(provider_id)
        except KeyError as exc:
            raise ToolValidationError(f"ToolProvider 不存在：{provider_id}") from exc
        tools = [self._tools.pop(name) for name in names if name in self._tools]
        if close:
            provider.close()
        return tools

    def close_providers(self) -> list[str]:
        """Close providers in reverse registration order; return failed provider ids."""
        failures: list[str] = []
        for provider_id, provider in reversed(list(self._providers.items())):
            try:
                provider.close()
            except Exception:
                failures.append(provider_id)
        self._providers.clear()
        self._provider_tools.clear()
        return failures

    def _validate_provider_tools(
        self,
        provider_id: str,
        tools: list[Tool],
        *,
        ignored_names: set[str],
    ) -> None:
        names: set[str] = set()
        for tool in tools:
            self._validate(tool)
            if tool.name in names:
                raise ToolValidationError(
                    f"ToolProvider {provider_id} 返回重复工具：{tool.name}"
                )
            if tool.name in self._tools and tool.name not in ignored_names:
                raise ToolValidationError(f"工具已注册：{tool.name}")
            names.add(tool.name)

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
        usable = {t["name"] for t in self.manifest() if t["enabled"] and t["available"]}
        return [tool.schema() for tool in self._tools.values() if tool.name in usable]

    def providers(self) -> list[ToolProviderProtocol]:
        return list(self._providers.values())
