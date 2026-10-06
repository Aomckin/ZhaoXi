from zhaoxi.cli import build_agent
from zhaoxi.config.settings import Settings
from zhaoxi.memory.models import MemoryCreate, MemoryQuery
from zhaoxi.memory.service import MemoryService
from zhaoxi.memory.sqlite import SQLiteMemoryRepository
from zhaoxi.permission.sqlite import SQLitePermissionStore
from zhaoxi.planner.sqlite import SQLitePlanStore
from zhaoxi.reflection.sqlite import SQLiteReflectionRepository
from zhaoxi.session.sqlite import SQLiteSessionStore


def test_build_agent_uses_persistent_reliability_stores(tmp_path, monkeypatch):
    monkeypatch.setenv("ZHAOXI_TOOL_LIFEHUD_ENABLED", "true")
    settings = Settings(
        _env_file=None,
        model_api_key="test-key",
        model_name="test-model",
        memory_db_path=str(tmp_path / "memory.db"),
        planner_db_path=str(tmp_path / "planner.db"),
        session_db_path=str(tmp_path / "session.db"),
        permission_db_path=str(tmp_path / "permission.db"),
        workflow_db_path=str(tmp_path / "workflow.db"),
        proactive_db_path=str(tmp_path / "proactive.db"),
        reflection_db_path=str(tmp_path / "reflection.db"),
        permission_audit_path=str(tmp_path / "audit" / "permission.jsonl"),
        backup_directory=str(tmp_path / "backups"),
    )

    first = build_agent(settings)
    first.conversation.add_user("持久会话")
    first.session_record.conversation = first.conversation
    first.session_store.save_sync(first.session_record)
    second = build_agent(settings)

    assert isinstance(second.planner.store, SQLitePlanStore)
    assert isinstance(second.session_store, SQLiteSessionStore)
    assert isinstance(second.tool_executor.gateway.store, SQLitePermissionStore)
    assert second.conversation.messages[-1].content == "持久会话"
    assert second.backup_manager.health()["memory"]["healthy"] is True
    assert second.capability_catalog["status"] == "ready"
    assert any(item["name"] == "lifehud" for item in second.capability_catalog["tools"])
    assert any(package["id"] == "lifehud-tool" for package in second.capability_catalog["packages"])
    assert isinstance(second.reflection.repository, SQLiteReflectionRepository)
    assert second.reflection_periods is not None


async def test_v1_fresh_data_backup_restore_round_trip(tmp_path):
    settings = Settings(
        _env_file=None,
        model_api_key="test-key",
        model_name="test-model",
        memory_db_path=str(tmp_path / "data" / "memory.db"),
        planner_db_path=str(tmp_path / "data" / "planner.db"),
        session_db_path=str(tmp_path / "data" / "session.db"),
        permission_db_path=str(tmp_path / "data" / "permission.db"),
        workflow_db_path=str(tmp_path / "data" / "workflow.db"),
        proactive_db_path=str(tmp_path / "data" / "proactive.db"),
        reflection_db_path=str(tmp_path / "data" / "reflection.db"),
        permission_audit_path=str(tmp_path / "data" / "permission.jsonl"),
        backup_directory=str(tmp_path / "backups"),
    )
    agent = build_agent(settings)
    memory = agent.context_builder.memory_retriever.service
    await memory.remember(MemoryCreate(content="v1 backup canary"))
    backup = agent.backup_manager.create()
    await memory.remember(MemoryCreate(content="created after backup"))

    safeguard = agent.backup_manager.restore(backup)
    restored = MemoryService(SQLiteMemoryRepository(settings.memory_db_path))

    assert (await restored.search(MemoryQuery(text="backup canary")))[0].record.content == "v1 backup canary"
    records = await restored.search(MemoryQuery(limit=20))
    assert "created after backup" not in {item.record.content for item in records}
    assert agent.backup_manager.verify(safeguard)["application_version"] == __import__("zhaoxi").__version__


def test_startup_recovers_activity_hot_journal_before_readonly_health(tmp_path, monkeypatch):
    import sqlite3
    from pathlib import Path
    import subprocess
    import sys
    from contextlib import closing
    import pytest

    settings = Settings(_env_file=None, model_api_key="test-key", model_name="test-model",
                        internal_activity_db_path=str(tmp_path / "activity.db"))
    # Crash a real writer after dirty pages spill; no production data or model call.
    subprocess.run([sys.executable, "-c", """
import os, sqlite3, sys
c = sqlite3.connect(sys.argv[1])
c.execute('PRAGMA journal_mode=DELETE')
c.execute('PRAGMA cache_size=1')
c.execute('CREATE TABLE crash_canary(value BLOB)')
c.executemany('INSERT INTO crash_canary VALUES (?)', [(b'a' * 4096,)] * 100)
c.commit()
c.execute('BEGIN IMMEDIATE')
c.execute('UPDATE crash_canary SET value=?', (b'b' * 4096,))
os._exit(0)
""", settings.internal_activity_db_path], check=True)
    assert Path(settings.internal_activity_db_path + "-journal").exists()
    with closing(sqlite3.connect(Path(settings.internal_activity_db_path).as_uri() + "?mode=ro", uri=True)) as db:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            db.execute("PRAGMA quick_check").fetchone()
    monkeypatch.setattr("zhaoxi.bootstrap.tools.discover_tool_packages", lambda **kwargs: [])
    agent = build_agent(settings)
    assert agent.provider is not None
    assert agent.internal_activity is not None
    assert agent.backup_manager.health()["internal_activity"]["healthy"] is True
    with closing(sqlite3.connect(settings.internal_activity_db_path)) as db:
        assert db.execute('SELECT DISTINCT substr(value,1,1) FROM crash_canary').fetchall() == [(b'a',)]


def test_corrupt_activity_database_still_blocks_startup(tmp_path, monkeypatch):
    import pytest
    from zhaoxi.errors import ConfigError
    path = tmp_path / "activity.db"
    path.write_bytes(b"not sqlite")
    settings = Settings(_env_file=None, model_api_key="test-key", model_name="test-model",
                        internal_activity_db_path=str(path))
    monkeypatch.setattr("zhaoxi.bootstrap.tools.discover_tool_packages", lambda **kwargs: [])
    with pytest.raises(ConfigError, match="内部活动数据初始化失败"):
        build_agent(settings)
    assert path.read_bytes() == b"not sqlite"
