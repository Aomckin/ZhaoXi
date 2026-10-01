"""ZhaoXi storage composition."""

from pathlib import Path
from zhaoxi.config.settings import Settings
from zhaoxi.reliability import DataStoreSpec
from zhaoxi.core.conversation import Conversation
from zhaoxi.permission.audit import JsonlAuditSink
from zhaoxi.permission.executor import ToolExecutor
from zhaoxi.permission.gateway import PermissionGateway
from zhaoxi.permission.models import PermissionLevel, PermissionStatus
from zhaoxi.permission.policy import DefaultPermissionPolicy
from zhaoxi.permission.sqlite import SQLitePermissionStore
from zhaoxi.tools.filesystem_access import load_filesystem_access
from zhaoxi.tools.builtin.save_emoji import SaveEmojiTool
from zhaoxi.session.base import Session
from zhaoxi.session.sqlite import SQLiteSessionStore


def build_storage_runtime(settings: Settings, registry, emoji_manager):
    policy_values = {
        PermissionLevel.READ: settings.permission_read_policy,
        PermissionLevel.WRITE: settings.permission_write_policy,
        PermissionLevel.DELETE: settings.permission_delete_policy,
        PermissionLevel.EXTERNAL_ACTION: settings.permission_external_action_policy,
        PermissionLevel.DANGEROUS: settings.permission_dangerous_policy,
    }
    policy = DefaultPermissionPolicy({
        level: PermissionStatus.REQUIRE_CONFIRMATION if value == "confirm" else PermissionStatus(value)
        for level, value in policy_values.items()
    })
    gateway = PermissionGateway(
        policy=policy,
        store=SQLitePermissionStore(settings.permission_db_path),
        audit=JsonlAuditSink(
            settings.permission_audit_path,
            max_bytes=settings.permission_audit_max_bytes,
            backup_count=settings.permission_audit_backup_count,
        ),
        confirmation_ttl_seconds=settings.permission_confirmation_ttl_seconds,
    )
    tool_executor = ToolExecutor(
        registry,
        gateway,
        max_output_chars=settings.permission_max_tool_output_chars,
        filesystem_write_roots=tuple(
            Path(item)
            for item in load_filesystem_access(Path(settings.filesystem_access_path))[
                "write_directories"
            ]
        ),
    )
    session_store = SQLiteSessionStore(
        settings.session_db_path, max_messages=settings.max_context_messages, media_directory=settings.media_directory
    )
    session_record = session_store.get_sync("local")
    if session_record is None:
        session_record = Session(
            id="local",
            conversation=Conversation(max_messages=settings.max_context_messages),
        )
        session_store.save_sync(session_record)
    conversation = session_record.conversation
    registry.register(SaveEmojiTool(emoji_manager, conversation))
    return gateway, tool_executor, session_store, session_record, conversation

# Keep active and legacy backup sources in one auditable registry.
def build_data_store_specs(settings: Settings, *, archive_enabled: bool) -> list[DataStoreSpec]:
    database_fields = (
        ("memory", "memory_db_path"),
        ("planner", "planner_db_path"),
        ("session", "session_db_path"),
        ("permission", "permission_db_path"),
        ("workflow", "workflow_db_path"),
        ("proactive", "proactive_db_path"),
        ("reflection", "reflection_db_path"),
        ("agenda", "agenda_db_path"),
        ("current_cognition", "current_cognition_db_path"),
    )
    specs = [DataStoreSpec(name, Path(getattr(settings, field))) for name, field in database_fields]
    for name, path in (
        ("decision_log", ".zhaoxi/decisions/decision_log.jsonl"),
        ("decision_overrides", ".zhaoxi/decisions/override_log.jsonl"),
        ("decision_rule_candidates", ".zhaoxi/decisions/rule_candidates.jsonl"),
    ):
        specs.append(DataStoreSpec(name, Path(path), kind="file"))
    specs.append(DataStoreSpec("internal_activity", Path(settings.internal_activity_db_path)))
    specs.append(DataStoreSpec("perception", Path(settings.perception_db_path)))
    specs.append(DataStoreSpec("experience", Path(".zhaoxi/experience.db")))
    # Legacy backup/restore only; neither source enters the current Context.
    specs.append(DataStoreSpec("short_term_memory", Path(settings.short_term_memory_db_path)))
    specs.append(DataStoreSpec("working_notes", Path(settings.working_notes_db_path)))
    specs.append(DataStoreSpec("permission_audit", Path(settings.permission_audit_path), kind="file"))
    if archive_enabled:
        specs.append(DataStoreSpec("archive", Path(settings.archive_db_path)))
    specs.append(DataStoreSpec("media",Path(settings.media_directory),kind="directory"))
    return specs