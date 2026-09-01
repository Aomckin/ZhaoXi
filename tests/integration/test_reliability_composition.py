from zhaoxi.cli import build_agent
from zhaoxi.config.settings import Settings
from zhaoxi.permission.sqlite import SQLitePermissionStore
from zhaoxi.planner.sqlite import SQLitePlanStore
from zhaoxi.session.sqlite import SQLiteSessionStore


def test_build_agent_uses_persistent_reliability_stores(tmp_path):
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
