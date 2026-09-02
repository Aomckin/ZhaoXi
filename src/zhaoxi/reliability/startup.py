"""Content-free startup diagnostics that work before the Agent can start."""

from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path
import os
import platform
import sys

from zhaoxi import __version__
from zhaoxi.config.settings import Settings
from zhaoxi.tools.packages import create_package_tools, discover_tool_packages


def _check(ok: bool, *, code: str, message: str, action: str | None = None) -> dict[str, object]:
    value: dict[str, object] = {"ok": ok, "code": code, "message": message}
    if action:
        value["action"] = action
    return value


def startup_diagnostics(settings: Settings, *, tool_root: str | Path = "tools") -> dict[str, object]:
    """Return bounded diagnostics without exposing secrets or user content."""
    checks: dict[str, dict[str, object]] = {}
    checks["python"] = _check(
        sys.version_info >= (3, 12),
        code="python_supported" if sys.version_info >= (3, 12) else "python_too_old",
        message=f"Python {platform.python_version()}",
        action=None if sys.version_info >= (3, 12) else "安装 Python 3.12 或更新版本。",
    )
    model_ready = bool(settings.model_api_key and settings.model_name)
    checks["model"] = _check(
        model_ready,
        code="model_configured" if model_ready else "model_config_missing",
        message="模型配置完整。" if model_ready else "缺少模型 API Key 或模型名称。",
        action=None if model_ready else "复制 .env.example 为 .env，并填写 ZHAOXI_MODEL_API_KEY 与 ZHAOXI_MODEL_NAME。",
    )

    data_root = Path(settings.memory_db_path).expanduser().resolve().parent
    existing_parent = data_root
    while not existing_parent.exists() and existing_parent.parent != existing_parent:
        existing_parent = existing_parent.parent
    writable = existing_parent.is_dir() and os.access(existing_parent, os.W_OK)
    checks["data_directory"] = _check(
        writable,
        code="data_directory_writable" if writable else "data_directory_unwritable",
        message=f"数据目录：{data_root}",
        action=None if writable else "选择当前用户可写的数据目录并更新数据库路径配置。",
    )

    packages = []
    package_errors: list[dict[str, str]] = []
    try:
        for package in discover_tool_packages(tool_root, errors=package_errors):
            tools = create_package_tools(package)
            packages.append({
                "id": package.package_id,
                "version": package.package_version,
                "tools": [tool.name for tool in tools],
            })
    except Exception as exc:
        package_errors.append({"source": "configuration", "error": type(exc).__name__})
    checks["tool_packages"] = _check(
        not package_errors,
        code="tool_packages_ready" if not package_errors else "tool_package_load_failed",
        message=f"已发现 {len(packages)} 个 Tool Package。" if not package_errors else f"有 {len(package_errors)} 个 Tool Package 无法加载。",
        action=None if not package_errors else "检查 Tool 包配置、版本和安装状态。",
    )

    optional = {
        "desktop": all(find_spec(name) is not None for name in ("webview", "pystray")),
        "voice_input": find_spec("sounddevice") is not None,
        "voice_output": find_spec("comtypes") is not None,
    }
    blockers = [name for name, value in checks.items() if not value["ok"] and name != "model"]
    status = "blocked" if blockers else ("ready" if model_ready else "needs_configuration")
    return {
        "status": status,
        "version": __version__,
        "platform": platform.system(),
        "checks": checks,
        "tool_packages": packages,
        "tool_package_errors": package_errors,
        "optional_features": optional,
    }
