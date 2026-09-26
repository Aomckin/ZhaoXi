"""ZhaoXi tools composition."""

import logging
from zhaoxi.config.settings import Settings
from zhaoxi.agenda.tools import create_agenda_tools
from zhaoxi.tools.builtin import create_builtin_tools
from zhaoxi.tools.registry import ToolRegistry
from zhaoxi.expression import EmojiManager, EmojiService
from zhaoxi.tools.packages import create_package_tool_providers, create_package_tools, discover_tool_packages
from zhaoxi.tools.packages import capability_enabled, config_for_package, declared_capabilities, package_enabled, sdk_compatible


def build_tool_runtime(settings: Settings, memory_service, archive_service, agenda_service):
    emoji_service = EmojiService(
        settings.emoji_registry_path,
        enabled=settings.emoji_enabled,
        recent_history_size=settings.emoji_recent_history_size,
        candidate_limit=settings.emoji_candidate_limit,
        min_match_score=settings.emoji_min_match_score,
    )
    emoji_manager = EmojiManager(emoji_service)
    registry = ToolRegistry(settings.tool_overrides_path)
    for tool in create_builtin_tools(memory_service, archive_service):
        registry.register(tool)
    for tool in create_agenda_tools(agenda_service):
        registry.register(tool)
    tool_package_errors: list[dict[str, str]] = []
    try:
        discovered_packages = discover_tool_packages(errors=tool_package_errors)
    except Exception as exc:
        discovered_packages = []
        tool_package_errors.append({"source": "discovery", "error": type(exc).__name__})
    tool_packages = []
    package_records = []
    package_capabilities: dict[str, dict[str, bool]] = {}
    for package in discovered_packages:
        try:
            config = config_for_package(package.package_id)
            if package.package_id == "mcp-tool":
                config.setdefault("filesystem_access_path", settings.filesystem_access_path)
            enabled = package_enabled(config)
            declaration = declared_capabilities(package)
            requirement = str(getattr(package, "requires_sdk", ""))
            if not sdk_compatible(requirement):
                raise ValueError(f"incompatible SDK requirement: {requirement}")
            flags = {
                name: enabled and capability_enabled(declaration, name, config)
                for name in type(declaration).model_fields
            }
            package_capabilities[package.package_id] = flags
            record = {
                "id": package.package_id,
                "version": package.package_version,
                "installed": True,
                "enabled": enabled,
                "configured": bool(config.get("base_url", True)),
                "reachable": None,
                "healthy": None,
                "requires_sdk": requirement,
                "capabilities": [name for name, value in flags.items() if value],
                "backoff_until": None,
            }
            package_records.append(record)
            configure = getattr(package, "configure", None)
            if configure is not None and (enabled or declaration.tool):
                configure(config)
            # Register ordinary tool definitions even when disabled by startup defaults.
            # Constructing a definition does not invoke it; providers still start only when enabled.
            if declaration.tool:
                for tool in create_package_tools(package, config):
                    tool.source = package.package_id
                    tool.default_enabled = flags["tool"]
                    registry.register(tool)
            if not enabled:
                continue
            if flags["tool"]:
                provider_tools = []
                for tool_provider in create_package_tool_providers(package, config):
                    try:
                        provider_tools.extend(registry.register_provider(tool_provider))
                    except Exception as exc:
                        try:
                            tool_provider.close()
                        except Exception:
                            pass
                        tool_package_errors.append({
                            "source": f"{package.package_id}:provider:{tool_provider.provider_id}",
                            "error": type(exc).__name__,
                        })
                record["provider_tools"] = [tool.name for tool in provider_tools]
            tool_packages.append(package)
        except Exception as exc:
            tool_package_errors.append({"source": package.package_id, "error": type(exc).__name__})
            logging.getLogger("TOOLS").warning(
                "tool package unavailable id=%s error=%s",
                package.package_id,
                type(exc).__name__,
            )
    return emoji_service, emoji_manager, registry, tool_packages, package_records, package_capabilities, tool_package_errors
