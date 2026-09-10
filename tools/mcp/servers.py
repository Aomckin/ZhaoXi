"""Local stdio server inventory for the installed MCP repositories."""

from __future__ import annotations

import os
from pathlib import Path
import shutil

from tools.mcp.provider import MCPServerSpec


def _required(path: Path, label: str) -> str:
    if not path.exists():
        raise FileNotFoundError(f"{label} 尚未安装：{path}")
    return str(path)


def _find_es_path(environment: dict[str, str] | None = None) -> str | None:
    """Locate the absolute ES CLI path, including winget portable installs."""
    env = os.environ if environment is None else environment
    configured = env.get("ES_PATH")
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_absolute() and candidate.is_file():
            return str(candidate)

    candidates = [
        Path(env.get("ProgramFiles", r"C:\Program Files")) / "Everything" / "es.exe",
        Path(env.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Everything"
        / "es.exe",
    ]
    local_app_data = env.get("LOCALAPPDATA")
    if local_app_data:
        local_root = Path(local_app_data)
        candidates.append(local_root / "Microsoft" / "WinGet" / "Links" / "es.exe")
        package_root = local_root / "Microsoft" / "WinGet" / "Packages"
        if package_root.is_dir():
            candidates.extend(sorted(package_root.glob("voidtools.Everything.Cli_*/es.exe")))
    user_profile = env.get("USERPROFILE")
    if user_profile:
        candidates.append(Path(user_profile) / "scoop" / "apps" / "everything" / "current" / "es.exe")

    return next((str(path.resolve()) for path in candidates if path.is_file()), None)


def installed_server_specs(root: Path, workspace_root: Path) -> list[MCPServerSpec]:
    node = shutil.which("node")
    if not node:
        raise FileNotFoundError("没有找到 Node.js")
    official = root / "modelcontextprotocol-servers" / "src"
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    memory_file = data / "memory.jsonl"
    playwright_output = data / "playwright"
    playwright_output.mkdir(parents=True, exist_ok=True)
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    playwright_args = [
        _required(root / "playwright-mcp" / "cli.js", "Playwright MCP"),
        "--headless",
        "--output-dir",
        str(playwright_output),
    ]
    if edge.exists():
        playwright_args.extend(("--browser", "msedge"))
    everything_environment = {}
    if es_path := _find_es_path():
        everything_environment["ES_PATH"] = es_path
    return [
        MCPServerSpec(
            "everything-search",
            node,
            (_required(root / "everything-mcp" / "bundle" / "index.js", "Everything MCP"),),
            root / "everything-mcp",
            everything_environment,
        ),
        MCPServerSpec(
            "reference-everything",
            node,
            (_required(official / "everything" / "dist" / "index.js", "Reference Everything"), "stdio"),
            official / "everything",
        ),
        MCPServerSpec(
            "filesystem",
            node,
            (_required(official / "filesystem" / "dist" / "index.js", "Filesystem MCP"), str(workspace_root)),
            official / "filesystem",
        ),
        MCPServerSpec(
            "memory",
            node,
            (_required(official / "memory" / "dist" / "index.js", "Memory MCP"),),
            official / "memory",
            {"MEMORY_FILE_PATH": str(memory_file)},
        ),
        MCPServerSpec(
            "sequential-thinking",
            node,
            (_required(official / "sequentialthinking" / "dist" / "index.js", "Sequential Thinking MCP"),),
            official / "sequentialthinking",
        ),
        *[
            MCPServerSpec(
                name,
                _required(official / name / ".venv" / "Scripts" / f"mcp-server-{name}.exe", f"{name} MCP"),
                (),
                official / name,
            )
            for name in ("fetch", "git", "time")
        ],
        MCPServerSpec("playwright", node, tuple(playwright_args), root / "playwright-mcp"),
    ]


def selected_server_specs(root: Path, config: dict[str, object]) -> list[MCPServerSpec]:
    workspace = Path(str(config.get("workspace_root") or os.getcwd())).resolve()
    selected_value = str(config.get("servers") or "all").strip()
    selected = {item.strip() for item in selected_value.split(",") if item.strip()}
    specs = installed_server_specs(root, workspace)
    if not selected or "all" in selected:
        return specs
    known = {spec.server_id for spec in specs}
    unknown = selected - known
    if unknown:
        raise ValueError(f"未知 MCP Server：{sorted(unknown)}")
    return [spec for spec in specs if spec.server_id in selected]
