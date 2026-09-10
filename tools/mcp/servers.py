"""Local stdio server inventory for the installed MCP repositories."""

from __future__ import annotations

import os
from pathlib import Path
import shutil

from tools.mcp.provider import MCPServerSpec


DEFAULT_SERVER_IDS = frozenset({"filesystem", "everything-search", "fetch", "time"})


def _required(path: Path, label: str) -> str:
    if not path.exists():
        raise FileNotFoundError(f"{label} 尚未安装：{path}")
    return str(path)


def _as_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = str(value).strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"无效布尔值：{value}")


def _config_value(config: dict[str, object], key: str, environment_key: str) -> object | None:
    value = config.get(key)
    return value if value is not None else os.environ.get(environment_key)


def _filesystem_allowed_directories(root: Path, config: dict[str, object]) -> tuple[str, ...]:
    configured = _config_value(
        config,
        "filesystem_allowed_dirs",
        "MCP_FILESYSTEM_ALLOWED_DIRS",
    )
    if configured is None or not str(configured).strip():
        sandbox = root / "data" / "filesystem"
        sandbox.mkdir(parents=True, exist_ok=True)
        return (str(sandbox.resolve()),)

    directories: list[str] = []
    for raw_path in str(configured).split(os.pathsep):
        if not raw_path.strip():
            continue
        path = Path(raw_path.strip()).expanduser().resolve()
        if not path.is_dir():
            raise FileNotFoundError(f"Filesystem MCP 允许目录不存在：{path}")
        directories.append(str(path))
    if not directories:
        raise ValueError("Filesystem MCP 至少需要一个允许目录")
    return tuple(dict.fromkeys(directories))


def _find_es_path(environment: dict[str, str] | None = None) -> str | None:
    """Locate the absolute ES CLI path, including winget portable installs."""
    env = os.environ if environment is None else environment
    configured = env.get("ES_PATH")
    if configured:
        candidate = Path(configured).expanduser()
        if not candidate.is_absolute():
            raise ValueError(f"ES_PATH 必须是绝对路径：{candidate}")
        if not candidate.is_file():
            raise FileNotFoundError(f"ES_PATH 不存在：{candidate}")
        return str(candidate.resolve())

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


def installed_server_specs(
    root: Path,
    filesystem_allowed_dirs: tuple[str, ...],
    everything_es_path: object | None = None,
) -> list[MCPServerSpec]:
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
    everything_environment: dict[str, str] = {}
    es_environment = dict(os.environ)
    if everything_es_path is not None and str(everything_es_path).strip():
        es_environment["ES_PATH"] = str(everything_es_path).strip()
    if es_path := _find_es_path(es_environment):
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
            (
                _required(official / "filesystem" / "dist" / "index.js", "Filesystem MCP"),
                *filesystem_allowed_dirs,
            ),
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
    allowed_directories = _filesystem_allowed_directories(root, config)
    everything_es_path = _config_value(config, "everything_es_path", "MCP_EVERYTHING_ES_PATH")
    selected_value = str(config.get("servers") or ",".join(sorted(DEFAULT_SERVER_IDS))).strip()
    selected = {item.strip() for item in selected_value.split(",") if item.strip()}
    specs = installed_server_specs(root, allowed_directories, everything_es_path)
    if not selected:
        selected = set(DEFAULT_SERVER_IDS)
    if "all" in selected:
        selected = {spec.server_id for spec in specs if spec.server_id != "playwright"}
    playwright_enabled = _as_bool(
        _config_value(config, "playwright_enabled", "MCP_PLAYWRIGHT_ENABLED")
    )
    selected.discard("playwright")
    if playwright_enabled:
        selected.add("playwright")
    known = {spec.server_id for spec in specs}
    unknown = selected - known
    if unknown:
        raise ValueError(f"未知 MCP Server：{sorted(unknown)}")
    return [spec for spec in specs if spec.server_id in selected]
