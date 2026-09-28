"""v1.2.9 composition and legacy boundary regression checks."""

import sqlite3
import tomllib
from pathlib import Path

import zhaoxi
from zhaoxi.bootstrap.runtime import build_agent
from zhaoxi.bootstrap.storage import build_data_store_specs
from zhaoxi.config.settings import Settings
from zhaoxi.core.reply import parse_reply


ROOT = Path(__file__).parents[2]


def test_release_version_is_consistent():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert metadata["project"]["version"] == zhaoxi.__version__ == "1.3.3"


def test_datastore_registry_covers_active_and_legacy_sources(tmp_path):
    settings = Settings(
        memory_db_path=str(tmp_path / "memory.db"),
        short_term_memory_db_path=str(tmp_path / "old-stm.db"),
        working_notes_db_path=str(tmp_path / "old-notes.db"),
    )
    specs = build_data_store_specs(settings, archive_enabled=True)
    by_name = {item.name: item for item in specs}
    assert len(by_name) == len(specs)
    assert {
        "memory", "session", "permission", "agenda", "current_cognition",
        "internal_activity", "decision_log", "proactive", "workflow", "reflection",
        "short_term_memory", "working_notes", "archive",
    } <= by_name.keys()
    assert by_name["memory"].path == tmp_path / "memory.db"
    assert by_name["short_term_memory"].path == tmp_path / "old-stm.db"
    assert by_name["working_notes"].path == tmp_path / "old-notes.db"
    assert "archive" not in {item.name for item in build_data_store_specs(settings, archive_enabled=False)}


def test_build_agent_attaches_current_components_without_legacy_context(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    legacy_path = tmp_path / "old-stm.db"
    with sqlite3.connect(legacy_path) as db:
        db.execute("CREATE TABLE short_term_memory (id INTEGER PRIMARY KEY, state_json TEXT)")
        db.execute("INSERT INTO short_term_memory VALUES (1, ?)", ('{"overview":"LEGACY_STM_CANARY"}',))
    settings = Settings(
        model_api_key="test-key", model_name="test-model", archive_enabled=False,
        memory_db_path=str(tmp_path / "memory.db"),
        planner_db_path=str(tmp_path / "planner.db"),
        session_db_path=str(tmp_path / "session.db"),
        permission_db_path=str(tmp_path / "permission.db"),
        workflow_db_path=str(tmp_path / "workflow.db"),
        proactive_db_path=str(tmp_path / "proactive.db"),
        reflection_db_path=str(tmp_path / "reflection.db"),
        agenda_db_path=str(tmp_path / "agenda.db"),
        current_cognition_db_path=str(tmp_path / "cognition.db"),
        internal_activity_db_path=str(tmp_path / "activity.db"),
        short_term_memory_db_path=str(legacy_path),
        working_notes_db_path=str(tmp_path / "old-notes.db"),
        permission_audit_path=str(tmp_path / "audit.jsonl"),
        backup_directory=str(tmp_path / "backups"),
    )
    agent = build_agent(settings)
    assert agent.registry is not None
    assert agent.cognitive is not None
    assert agent.decision_service is not None
    assert agent.decision_service.rules.directory == ROOT / "data" / "decisions" / "rules"
    assert agent.internal_activity is not None
    assert agent.current_cognition is agent.context_builder.current_cognition_service
    context = agent.context_builder.build(agent.conversation)[0].content
    assert "[Current Cognition]" in context
    assert "LEGACY_STM_CANARY" not in context
    assert "Working Notes" not in context
    names = {tool.name for tool in agent.registry.list()}
    assert "save_emoji" in names
    assert "send_emoji" not in names
    assert parse_reply("好。[emoji:开心]").segments[-1].type == "emoji"
