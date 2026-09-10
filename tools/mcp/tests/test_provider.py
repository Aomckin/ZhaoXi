from pathlib import Path
import asyncio
import shutil

from tools.mcp.provider import MCPServerSpec, MCPToolProvider
from tools.mcp.servers import _find_es_path, selected_server_specs
from zhaoxi.cli import build_agent
from zhaoxi.config.settings import Settings
from zhaoxi.permission.executor import ToolExecutor
from zhaoxi.permission.models import InvocationOrigin
from zhaoxi.tools.registry import ToolRegistry


def provider():
    node = shutil.which("node")
    assert node
    fixture = Path(__file__).with_name("fake_server.mjs")
    return MCPToolProvider(MCPServerSpec("fake", node, (str(fixture),), fixture.parent))


def test_find_es_path_supports_winget_portable_package(tmp_path):
    package = tmp_path / "Microsoft" / "WinGet" / "Packages" / "voidtools.Everything.Cli_test"
    package.mkdir(parents=True)
    executable = package / "es.exe"
    executable.touch()

    assert _find_es_path({"LOCALAPPDATA": str(tmp_path)}) == str(executable.resolve())


def test_default_servers_use_an_isolated_filesystem_sandbox(monkeypatch, tmp_path):
    monkeypatch.delenv("MCP_FILESYSTEM_ALLOWED_DIRS", raising=False)
    monkeypatch.delenv("MCP_PLAYWRIGHT_ENABLED", raising=False)
    root = Path(__file__).parents[1]

    specs = selected_server_specs(root, {})

    assert {spec.server_id for spec in specs} == {
        "filesystem",
        "everything-search",
        "fetch",
        "time",
    }
    filesystem = next(spec for spec in specs if spec.server_id == "filesystem")
    assert filesystem.arguments[1:] == (str((root / "data" / "filesystem").resolve()),)
    assert str(Path.cwd().resolve()) not in filesystem.arguments


def test_filesystem_directories_and_playwright_have_independent_switches(monkeypatch, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv("MCP_FILESYSTEM_ALLOWED_DIRS", str(allowed))
    monkeypatch.setenv("MCP_PLAYWRIGHT_ENABLED", "true")
    root = Path(__file__).parents[1]

    specs = selected_server_specs(root, {"servers": "filesystem,memory"})

    assert {spec.server_id for spec in specs} == {"filesystem", "memory", "playwright"}
    filesystem = next(spec for spec in specs if spec.server_id == "filesystem")
    assert filesystem.arguments[1:] == (str(allowed.resolve()),)
    playwright = next(spec for spec in specs if spec.server_id == "playwright")
    assert "--extension" in playwright.arguments
    assert "--headless" not in playwright.arguments
    assert "--browser" not in playwright.arguments


def agent_settings(tmp_path):
    return Settings(
        _env_file=None,
        model_api_key="test",
        model_name="test",
        memory_db_path=str(tmp_path / "memory.db"),
        archive_db_path=str(tmp_path / "archive.db"),
        archive_directory=str(tmp_path / "archive"),
        planner_db_path=str(tmp_path / "planner.db"),
        session_db_path=str(tmp_path / "session.db"),
        permission_db_path=str(tmp_path / "permission.db"),
        permission_audit_path=str(tmp_path / "audit.jsonl"),
        workflow_db_path=str(tmp_path / "workflow.db"),
        reflection_db_path=str(tmp_path / "reflection.db"),
        proactive_db_path=str(tmp_path / "proactive.db"),
        backup_directory=str(tmp_path / "backups"),
    )


def test_mcp_tools_are_independent_registry_entries_with_native_permissions():
    asyncio.run(_exercise_independent_tools())


async def _exercise_independent_tools():
    registry = ToolRegistry()
    tools = registry.register_provider(provider())
    assert [tool.name for tool in tools] == ["mcp_fake_lookup", "mcp_fake_change"]
    assert tools[0].schema()["function"]["parameters"]["required"] == ["query"]

    executor = ToolExecutor(registry)
    read = await executor.execute(
        "mcp_fake_lookup",
        {"query": "answer"},
        request_id="read",
        origin=InvocationOrigin.AGENT,
    )
    write = await executor.execute(
        "mcp_fake_change",
        {"value": 42},
        request_id="write",
        origin=InvocationOrigin.AGENT,
    )
    assert read.result and read.result.success
    assert read.result.data == {"arguments": {"query": "answer"}}
    assert write.waiting_for_permission
    assert write.request.permission.value == "write"
    assert registry.close_providers() == []


def test_mcp_schema_validation_happens_before_remote_call():
    asyncio.run(_exercise_invalid_schema())


async def _exercise_invalid_schema():
    registry = ToolRegistry()
    registry.register_provider(provider())
    result = await ToolExecutor(registry).execute(
        "mcp_fake_lookup",
        {"query": "", "unknown": True},
        request_id="invalid",
        origin=InvocationOrigin.AGENT,
    )
    assert result.result and not result.result.success
    assert result.result.content == "工具参数无效。"
    registry.close_providers()


def test_build_agent_registers_each_selected_mcp_tool_without_special_agent_path(monkeypatch, tmp_path):
    monkeypatch.setenv("ZHAOXI_TOOL_MCP_ENABLED", "true")
    monkeypatch.setenv("ZHAOXI_TOOL_MCP_SERVERS", "time")
    monkeypatch.setenv("ZHAOXI_TOOL_LIFEHUD_ENABLED", "false")
    agent = build_agent(agent_settings(tmp_path))
    names = {tool.name for tool in agent.registry.list()}
    assert "mcp_time_get_current_time" in names
    assert "mcp_time_convert_time" in names
    assert {provider.provider_id for provider in agent.registry.providers()} == {"mcp:time"}
    assert agent.registry.close_providers() == []
