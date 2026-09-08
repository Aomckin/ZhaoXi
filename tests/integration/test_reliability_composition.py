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
    assert second.capability_catalog["packages"][0]["id"] == "lifehud-tool"
    assert isinstance(second.reflection.repository, SQLiteReflectionRepository)
    assert second.reflection_periods is not None


async def test_v1_fresh_data_backup_restore_round_trip(tmp_path):
    settings = Settings(
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
