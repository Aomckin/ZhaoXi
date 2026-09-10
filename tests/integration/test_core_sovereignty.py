import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.lifehud_tool.package import create_package
from tools.lifehud_tool.proactive import LifeHudSensor
from zhaoxi.cli import build_agent
from zhaoxi.config.settings import Settings
from zhaoxi.core.facts import DomainAuthorityPolicy, FactDomain, FactObservation
from zhaoxi.proactive.continuation import ConversationContinuation
from zhaoxi.proactive.interaction import Interaction, InteractionState, Interruptibility
from zhaoxi.reliability.startup import startup_diagnostics
from zhaoxi.sdk import SDK_VERSION, SignalAggregator, StateSignal


NOW = datetime(2026, 9, 7, 12, tzinfo=UTC)


def settings(tmp_path):
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


def test_lifehud_can_be_completely_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("ZHAOXI_TOOL_LIFEHUD_ENABLED", "false")
    agent = build_agent(settings(tmp_path))
    record = next(item for item in agent.tool_packages if item["id"] == "lifehud-tool")
    assert record["installed"] is True and record["enabled"] is False
    assert record["capabilities"] == []
    assert "lifehud" not in [tool.name for tool in agent.registry.list()]
    assert not any(item.id.startswith("lifehud.") for item in agent.workflow.registry.list())
    assert "lifehud-tool" not in agent.tool_package_instances


def test_core_runs_when_no_tool_package_is_installed(monkeypatch, tmp_path):
    monkeypatch.setattr("zhaoxi.cli.discover_tool_packages", lambda **kwargs: [])
    agent = build_agent(settings(tmp_path))
    assert agent.tool_packages == []
    assert "人格设定" in agent.context_builder.personality_prompt
    assert "表达方式" in agent.context_builder.expression_prompt
    assert agent.context_builder.character_prompt.index("人格设定") < agent.context_builder.character_prompt.index("表达方式")
    assert agent.proactive_state is not None
    assert agent.context_builder.memory_retriever is not None
    assert agent.archive is not None
    assert agent.reflection is not None


def test_disabled_package_diagnostics_performs_zero_network_access(monkeypatch, tmp_path):
    monkeypatch.setenv("ZHAOXI_TOOL_LIFEHUD_ENABLED", "false")
    monkeypatch.setattr("tools.lifehud_tool.package.httpx.get", lambda *args, **kwargs: pytest.fail("network accessed"))
    result = startup_diagnostics(settings(tmp_path))
    package = next(item for item in result["tool_packages"] if item["id"] == "lifehud-tool")
    assert package["enabled"] is False
    assert package["reachable"] is package["healthy"] is None
    assert result["status"] == "ready"


def test_unreachable_package_is_diagnostic_not_core_blocker(monkeypatch, tmp_path):
    monkeypatch.setenv("ZHAOXI_TOOL_LIFEHUD_ENABLED", "true")
    monkeypatch.setattr("tools.lifehud_tool.package.httpx.get", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")))
    result = startup_diagnostics(settings(tmp_path))
    package = next(item for item in result["tool_packages"] if item["id"] == "lifehud-tool")
    assert package["enabled"] and package["configured"]
    assert package["reachable"] is package["healthy"] is False
    assert result["status"] == "ready"


def test_capabilities_can_be_disabled_independently(monkeypatch, tmp_path):
    monkeypatch.setenv("ZHAOXI_TOOL_LIFEHUD_ENABLED", "true")
    monkeypatch.setenv("ZHAOXI_TOOL_LIFEHUD_PROACTIVE_ENABLED", "false")
    monkeypatch.setenv("ZHAOXI_TOOL_LIFEHUD_REFLECTION_ENABLED", "false")
    monkeypatch.setenv("ZHAOXI_TOOL_LIFEHUD_WORKFLOW_ENABLED", "false")
    agent = build_agent(settings(tmp_path))
    package = next(item for item in agent.tool_packages if item["id"] == "lifehud-tool")
    assert "tool" in package["capabilities"]
    assert "state_signal_provider" in package["capabilities"]
    assert "proactive_provider" not in package["capabilities"]
    assert "reflection_provider" not in package["capabilities"]
    assert "workflow" not in package["capabilities"]
    assert "lifehud" in [tool.name for tool in agent.registry.list()]
    assert not any(item.id.startswith("lifehud.") for item in agent.workflow.registry.list())


def test_sdk_and_lifehud_declare_a_single_capability_source():
    package = create_package()
    assert SDK_VERSION == "1.1.0"
    assert package.requires_sdk == ">=1,<2"
    assert package.capability_declaration().state_signal_provider
    tree = ast.parse(Path("tools/lifehud_tool/package.py").read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "LifeHudToolPackage")
    assert sum(isinstance(node, ast.FunctionDef) and node.name == "capabilities" for node in cls.body) == 1
    tool = package.create_tools({})[0]
    assert tool.side_effects_for({"operation": "focus.start"}) == {"external_service_write"}


def test_core_has_no_concrete_lifehud_import_and_package_uses_public_sdk():
    for path in Path("src/zhaoxi").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = [
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        ]
        assert not any(name.startswith("tools.lifehud_tool") for name in imports), path
    for path in Path("tools/lifehud_tool").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert not any(name.startswith("zhaoxi.") and name != "zhaoxi.sdk" for name in imports), path


def test_signal_aggregation_keeps_conversation_state_independent():
    interaction = Interaction()
    interaction.interact(NOW)
    interaction.observe_signals([StateSignal(
        type="attention.focus", value="active", source="lifehud",
        observed_at=NOW, expires_at=NOW + timedelta(minutes=3), priority="high",
    )], NOW)
    assert interaction.state is InteractionState.ACTIVE
    assert interaction.interruptibility is Interruptibility.LOW
    assert interaction.diagnostics(NOW)["signal_sources"] == ["lifehud"]


def test_signal_aggregator_resolves_priority_confidence_and_ttl():
    aggregator = SignalAggregator()
    aggregator.update([
        StateSignal(type="attention.focus", value="inactive", source="weak", observed_at=NOW,
                    expires_at=NOW + timedelta(minutes=1), confidence=.4),
        StateSignal(type="attention.focus", value="active", source="strong", observed_at=NOW,
                    expires_at=NOW + timedelta(minutes=2), confidence=1, priority="high"),
    ], NOW)
    assert aggregator.resolve("attention.focus", NOW).value == "active"
    assert aggregator.resolve("attention.focus", NOW + timedelta(minutes=3)) is None


def test_continuation_has_silence_cooldown_budget_and_open_thread():
    interaction = Interaction()
    interaction.interact(NOW)
    continuation = ConversationContinuation(silence_minutes=2, cooldown_minutes=5, budget=2)
    continuation.note_user_message("我去让 Codex 跑一下。", NOW)
    assert continuation.candidate(NOW + timedelta(minutes=1), interaction) is None
    candidate = continuation.candidate(NOW + timedelta(minutes=2), interaction)
    assert candidate is not None
    continuation.delivered(NOW + timedelta(minutes=2), interaction)
    assert interaction.continuation_count == 1
    continuation.note_user_message("我再去试试。", NOW + timedelta(minutes=3))
    assert continuation.candidate(NOW + timedelta(minutes=4), interaction) is None


def test_domain_authority_preserves_both_sources_and_resolves_by_domain():
    policy = DomainAuthorityPolicy()
    values = [
        FactObservation(value="about two hours", source="memory", source_kind="memory", domain="structured_life", observed_at=NOW),
        FactObservation(value="91 minutes", source="lifehud", source_kind="structured_tool", domain="structured_life", observed_at=NOW),
        FactObservation(value="felt determined", source="memory", source_kind="memory", domain="experience", observed_at=NOW),
        FactObservation(value="focus record", source="lifehud", source_kind="structured_tool", domain="experience", observed_at=NOW),
    ]
    assert len(values) == 4
    assert policy.resolve(values, FactDomain.STRUCTURED_LIFE).source == "lifehud"
    assert policy.resolve(values, FactDomain.EXPERIENCE).source == "memory"


@pytest.mark.asyncio
async def test_lifehud_provider_uses_progressive_backoff_and_recovers():
    class Client:
        calls = 0
        async def focus(self):
            self.calls += 1
            if self.calls < 3:
                raise RuntimeError("offline")
            return SimpleNamespace(focus=SimpleNamespace(active=None, effectiveMinutes=0))
        async def tasks(self):
            return SimpleNamespace(date=NOW.date(), tasks=SimpleNamespace(items=[], completed=0))
    client = Client()
    provider = LifeHudSensor(client)
    with pytest.raises(RuntimeError):
        await provider.collect_signals(NOW)
    assert provider.next_poll == NOW + timedelta(minutes=2)
    assert await provider.collect_signals(NOW + timedelta(minutes=1)) == []
    with pytest.raises(RuntimeError):
        await provider.collect_signals(NOW + timedelta(minutes=2))
    assert provider.next_poll == NOW + timedelta(minutes=7)
    signals = await provider.collect_signals(NOW + timedelta(minutes=7))
    assert signals[0].value == "inactive"
    assert provider.healthy is provider.reachable is True
    assert provider.failures == 0
