"""Thin interactive command-line interface."""

import asyncio
import logging
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from uuid import uuid4

from zhaoxi.config.logging import configure_logging
from zhaoxi.config.settings import Settings
from zhaoxi.cognitive.coordinator import CognitiveCoordinator
from zhaoxi.cognitive.memory_decision import AutoMemory
from zhaoxi.cognitive.router import CognitiveRouter
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.errors import ConfigError, ZhaoxiError
from zhaoxi.models.openai_compatible import OpenAICompatibleProvider
from zhaoxi.models.resilient import ResilientProvider
from zhaoxi.memory.models import MemoryQuery, MemoryStatus
from zhaoxi.memory.lifecycle import MemoryLifecyclePolicy
from zhaoxi.memory.retrieval import MemoryRetriever
from zhaoxi.memory.service import MemoryService
from zhaoxi.memory.sqlite import SQLiteMemoryRepository
from zhaoxi.personality.loader import PersonalityLoader
from zhaoxi.planner.runtime import PlannerRuntime
from zhaoxi.planner.sqlite import SQLitePlanStore
from zhaoxi.planner.trace import TraceRecorder
from zhaoxi.permission.audit import JsonlAuditSink
from zhaoxi.permission.executor import ToolExecutor
from zhaoxi.permission.gateway import PermissionGateway
from zhaoxi.permission.models import PermissionLevel, PermissionStatus
from zhaoxi.permission.policy import DefaultPermissionPolicy
from zhaoxi.permission.sqlite import SQLitePermissionStore
from zhaoxi.proactive import (
    InboxNotificationSink,
    InterruptPolicy,
    PolicyState,
    Priority,
    ProactiveRuntime,
    Schedule,
    ScheduleKind,
    Scheduler,
    SQLiteProactiveStore,
    Subscription,
)
from zhaoxi.tools.builtin import create_builtin_tools
from zhaoxi.tools.registry import ToolRegistry
from zhaoxi.tools.integrations.lifehud import (
    LifeHudClient,
    create_lifehud_context_tools,
    create_lifehud_focus_tools,
)
from zhaoxi.workflow.loader import WorkflowLoader
from zhaoxi.workflow.registry import WorkflowRegistry
from zhaoxi.workflow.runtime import WorkflowRuntime
from zhaoxi.workflow.sqlite import SQLiteWorkflowStore
from zhaoxi.session.base import Session
from zhaoxi.session.sqlite import SQLiteSessionStore
from zhaoxi.reliability import BackupManager, DataStoreSpec, RetryPolicy


def build_agent(settings: Settings) -> ZhaoxiAgent:
    """Wire v0.2 dependencies at the application boundary."""
    settings.validate_model_config()
    primary_provider = OpenAICompatibleProvider(
        base_url=settings.model_base_url,
        api_key=settings.model_api_key,
        model=settings.model_name,
        timeout=settings.request_timeout_seconds,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
    )
    providers = [primary_provider]
    if settings.model_fallback_name:
        providers.append(OpenAICompatibleProvider(
            base_url=settings.model_fallback_base_url,
            api_key=settings.model_fallback_api_key,
            model=settings.model_fallback_name,
            timeout=settings.request_timeout_seconds,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
        ))
    provider = ResilientProvider(
        providers,
        retry_policy=RetryPolicy(
            max_attempts=settings.retry_max_attempts,
            base_delay_seconds=settings.retry_base_delay_seconds,
            max_delay_seconds=settings.retry_max_delay_seconds,
        ),
        failure_threshold=settings.provider_failure_threshold,
        cooldown_seconds=settings.provider_cooldown_seconds,
        max_calls=settings.request_max_model_calls,
        max_total_tokens=settings.request_max_total_tokens,
    )
    memory_service = MemoryService(
        SQLiteMemoryRepository(settings.memory_db_path),
        MemoryLifecyclePolicy(
            importance_keep_threshold=settings.memory_importance_keep_threshold,
            relevance_active_threshold=settings.memory_relevance_active_threshold,
            importance_forget_threshold=settings.memory_importance_forget_threshold,
            relevance_forget_threshold=settings.memory_relevance_forget_threshold,
            relevance_decay_per_day=settings.memory_relevance_decay_per_day,
            relevance_access_boost=settings.memory_relevance_access_boost,
            cold_archive_after_days=settings.memory_cold_archive_after_days,
        ),
    )
    memory_retriever = MemoryRetriever(
        memory_service,
        limit=settings.memory_retrieval_limit,
        max_chars=settings.memory_context_max_chars,
    )
    registry = ToolRegistry()
    for tool in create_builtin_tools(memory_service):
        registry.register(tool)
    if settings.workflow_enabled:
        lifehud_client = LifeHudClient(
            settings.lifehud_base_url,
            context_path=settings.lifehud_context_path,
            schema_version=settings.lifehud_schema_version,
            timeout=settings.lifehud_timeout_seconds,
            max_retries=settings.lifehud_max_retries,
            display_timezone=settings.lifehud_display_timezone,
        )
        for tool in [
            *create_lifehud_context_tools(lifehud_client),
            *create_lifehud_focus_tools(lifehud_client),
        ]:
            registry.register(tool)
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
    )
    session_store = SQLiteSessionStore(
        settings.session_db_path, max_messages=settings.max_context_messages
    )
    session_record = session_store.get_sync("local")
    if session_record is None:
        session_record = Session(
            id="local",
            conversation=Conversation(max_messages=settings.max_context_messages),
        )
        session_store.save_sync(session_record)
    conversation = session_record.conversation
    context_builder = ContextBuilder(
        PersonalityLoader.load_prompt(), memory_retriever=memory_retriever
    )
    planner = None
    if settings.planner_enabled:
        planner = PlannerRuntime(
            provider=provider,
            registry=registry,
            context_builder=context_builder,
            conversation=conversation,
            store=SQLitePlanStore(settings.planner_db_path),
            trace=TraceRecorder(settings.planner_trace_max_events),
            max_steps=settings.planner_max_steps,
            max_replans=settings.planner_max_replans,
            max_attempts_per_step=settings.planner_max_attempts_per_step,
            step_timeout_seconds=settings.planner_step_timeout_seconds,
            total_timeout_seconds=settings.planner_total_timeout_seconds,
            tool_executor=tool_executor,
        )
    workflow = None
    if settings.workflow_enabled:
        workflow_registry = WorkflowRegistry(registry)
        for definition in WorkflowLoader().load_directory(settings.workflow_directory):
            workflow_registry.register(definition)
        workflow = WorkflowRuntime(
            workflow_registry,
            tool_executor,
            SQLiteWorkflowStore(settings.workflow_db_path),
            max_steps=settings.workflow_max_steps,
            max_events=settings.workflow_max_events,
        )
    proactive = None
    proactive_scheduler = None
    proactive_state = None
    if settings.proactive_enabled:
        proactive_store = SQLiteProactiveStore(settings.proactive_db_path)
        proactive_state = PolicyState(enabled=True)
        proactive = ProactiveRuntime(
            proactive_store,
            InboxNotificationSink(proactive_store),
            InterruptPolicy(
                night_start=time(settings.proactive_night_start_hour),
                night_end=time(settings.proactive_night_end_hour),
            ),
            [Subscription(
                subscription_id="builtin.reminder",
                event_type="reminder.due",
                notification_template="提醒：{payload[text]}",
                default_priority=Priority.NOTICE,
            )],
        )
        proactive_scheduler = Scheduler(
            proactive_store,
            max_per_tick=settings.proactive_max_events_per_tick,
            misfire_grace_seconds=settings.proactive_misfire_grace_seconds,
        )
    agent = ZhaoxiAgent(
        provider=provider,
        registry=registry,
        context_builder=context_builder,
        conversation=conversation,
        max_steps=settings.max_agent_steps,
        timeout_seconds=settings.request_timeout_seconds,
        planner=planner,
        tool_executor=tool_executor,
        workflow=workflow,
        proactive=proactive,
        proactive_scheduler=proactive_scheduler,
        proactive_state=proactive_state,
    )
    agent.session_store = session_store
    agent.session_record = session_record
    agent.metrics = provider.metrics
    agent.backup_manager = BackupManager(
        settings.backup_directory,
        [
            DataStoreSpec("memory", Path(settings.memory_db_path)),
            DataStoreSpec("planner", Path(settings.planner_db_path)),
            DataStoreSpec("session", Path(settings.session_db_path)),
            DataStoreSpec("permission", Path(settings.permission_db_path)),
            DataStoreSpec("workflow", Path(settings.workflow_db_path)),
            DataStoreSpec("proactive", Path(settings.proactive_db_path)),
            DataStoreSpec("reflection", Path(settings.reflection_db_path)),
            DataStoreSpec("permission_audit", Path(settings.permission_audit_path), kind="file"),
        ],
        retention_count=settings.backup_retention_count,
    )
    unhealthy = [
        name for name, status in agent.backup_manager.health().items()
        if status["exists"] and not status["healthy"]
    ]
    if unhealthy:
        raise ConfigError(f"数据健康检查失败：{', '.join(unhealthy)}。请从已验证备份恢复。")
    # Ad-hoc Agent waits cannot safely reconstruct the exact provider tool-call
    # transcript after a crash. Fail them closed; Planner and Workflow waits
    # retain their own recoverable state.
    for confirmation_id, pending in list(gateway.store.pending.items()):
        if pending.resolved or pending.request.origin is not InvocationOrigin.AGENT:
            continue
        gateway.deny(confirmation_id)
    if settings.cognitive_router_enabled:
        agent.cognitive = CognitiveCoordinator(
            agent=agent,
            router=CognitiveRouter(provider),
            auto_memory=AutoMemory(provider, memory_service) if settings.auto_memory_enabled else None,
        )
    return agent


async def interactive() -> None:
    settings = Settings()
    if hasattr(settings, "log_path"):
        configure_logging(
            settings.log_level,
            path=settings.log_path,
            max_bytes=settings.log_max_bytes,
            backup_count=settings.log_backup_count,
        )
    else:
        configure_logging(settings.log_level)
    try:
        agent = build_agent(settings)
    except ZhaoxiError as exc:
        print(f"配置错误：{exc}")
        return

    print(
        "Zhaoxi v0.9 · Reliability\n"
        "输入 /diagnostics 检查运行状态，/backup 创建备份，/exit 退出。"
    )
    while True:
        try:
            text = input("\nYou > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n朝汐 > 再见，暗苟。")
            return
        if not text:
            continue
        if text == "/exit":
            print("朝汐 > 再见，暗苟。")
            return
        if text == "/clear":
            agent.conversation.clear()
            agent.session_record.conversation = agent.conversation
            await agent.session_store.save(agent.session_record)
            print("朝汐 > 当前会话已清空。")
            continue
        if text == "/diagnostics":
            print({
                "version": __import__("zhaoxi").__version__,
                "storage": agent.backup_manager.health(),
            })
            continue
        if text == "/backup":
            try:
                backup = await asyncio.to_thread(agent.backup_manager.create)
                print(f"朝汐 > 备份已完成并验证：{backup.name}")
            except Exception as exc:
                print(f"朝汐 > 备份失败：{exc}")
            continue
        if text.startswith("/backup verify "):
            backup_id = text.removeprefix("/backup verify ").strip()
            try:
                await asyncio.to_thread(
                    agent.backup_manager.verify,
                    Path(agent.backup_manager.backup_directory) / backup_id,
                )
                print(f"朝汐 > 备份校验通过：{backup_id}")
            except Exception as exc:
                print(f"朝汐 > 备份校验失败：{exc}")
            continue
        if text.startswith("/restore "):
            backup_id = text.removeprefix("/restore ").strip()
            try:
                safeguard = await asyncio.to_thread(
                    agent.backup_manager.restore,
                    Path(agent.backup_manager.backup_directory) / backup_id,
                )
                print(f"朝汐 > 恢复完成；恢复前保护备份：{safeguard.name}。请重启朝汐。")
                return
            except Exception as exc:
                print(f"朝汐 > 恢复失败：{exc}")
            continue
        if text == "/tools":
            print("可用工具：" + "、".join(
                f"{tool.name}[{tool.permission.value}]" for tool in agent.registry.list()
            ))
            continue
        if text.startswith(("/permissions", "/approve", "/deny", "/revoke", "/audit")):
            try:
                await handle_permission_command(agent, text)
            except ZhaoxiError as exc:
                print(f"朝汐 > 权限操作失败：{exc}")
            continue
        if text.startswith("/plan") or text.startswith("/resume") or text.startswith("/cancel") or text.startswith("/trace"):
            try:
                await handle_planner_command(agent, text)
            except ZhaoxiError as exc:
                print(f"朝汐 > 规划任务失败：{exc}")
            continue
        if text.startswith("/memory"):
            try:
                await handle_memory_command(agent, text)
            except ZhaoxiError as exc:
                print(f"朝汐 > 记忆操作失败：{exc}")
            continue
        if text.startswith("/workflow"):
            try:
                await handle_workflow_command(agent, text)
            except (ZhaoxiError, ValueError, KeyError) as exc:
                print(f"朝汐 > Workflow 操作失败：{exc}")
            continue
        if text.startswith("/proactive"):
            try:
                await handle_proactive_command(agent, text)
            except (ZhaoxiError, ValueError, KeyError) as exc:
                print(f"朝汐 > 主动任务操作失败：{exc}")
            continue
        try:
            response = await agent.run_natural(text)
            print(f"朝汐 > {response.content}")
        except ZhaoxiError as exc:
            print(f"朝汐 > 这次没有顺利完成：{exc}")
        except Exception as exc:
            trace_id = uuid4().hex
            error_logger = logging.getLogger("ERROR")
            if error_logger.isEnabledFor(logging.DEBUG):
                error_logger.exception("unexpected CLI failure trace_id=%s", trace_id)
            else:
                error_logger.error(
                    "unexpected CLI failure trace_id=%s type=%s",
                    trace_id,
                    type(exc).__name__,
                )
            print(f"朝汐 > 遇到了未预期的内部错误，请稍后重试。（追踪号：{trace_id}）")


async def handle_workflow_command(agent: ZhaoxiAgent, text: str) -> None:
    runtime = agent.workflow
    if runtime is None:
        print("朝汐 > Workflow 未启用。")
        return
    import json

    parts = text.split(maxsplit=3)
    if len(parts) == 1:
        for definition in runtime.registry.list():
            print(f"{definition.id}@{definition.version} {definition.name}")
        return
    command = parts[1]
    if command == "show" and len(parts) >= 3:
        print(runtime.registry.get(parts[2]).model_dump_json(indent=2))
        return
    if command == "run" and len(parts) >= 3:
        inputs = json.loads(parts[3]) if len(parts) == 4 else {}
        run = await runtime.start(parts[2], inputs)
        print(f"朝汐 > [{run.id}] {run.status.value} {json.dumps(run.result, ensure_ascii=False)}")
        return
    if command == "status" and len(parts) >= 3:
        print((await runtime.get(parts[2])).model_dump_json(indent=2))
        return
    if command in {"approve", "deny", "pause", "resume", "cancel"} and len(parts) >= 3:
        run = await getattr(runtime, command)(parts[2])
        print(f"朝汐 > [{run.id}] {run.status.value}")
        return
    if command == "input" and len(parts) == 4:
        run = await runtime.provide_input(parts[2], json.loads(parts[3]))
        print(f"朝汐 > [{run.id}] {run.status.value}")
        return
    if command == "history":
        for run in await runtime.history():
            print(f"{run.id} [{run.status.value}] {run.workflow_id}@{run.workflow_version}")
        return
    print("用法：/workflow [show|run|status|input|approve|deny|pause|resume|cancel|history] ...")


async def handle_memory_command(agent: ZhaoxiAgent, text: str) -> None:
    """Inspect memory without routing maintenance commands through the model."""
    retriever = agent.context_builder.memory_retriever
    if retriever is None:
        print("朝汐 > 长期记忆未启用。")
        return
    parts = text.split(maxsplit=2)
    if len(parts) == 2 and parts[1] == "maintain":
        changed = await retriever.service.maintain()
        print(f"朝汐 > Memory maintenance 完成，更新了 {len(changed)} 条记忆。")
        return
    if len(parts) == 3 and parts[1] == "search":
        results = await retriever.service.search(MemoryQuery(text=parts[2], limit=20))
        if not results:
            print("朝汐 > 没有找到相关记忆。")
            return
        for item in results:
            record = item.record
            print(f"{record.id} [{record.kind.value}] {record.created_at.isoformat()} {record.content}")
        return
    if len(parts) == 3 and parts[1] == "get":
        record = await retriever.service.get(parts[2])
        if record is None:
            print("朝汐 > 没有找到这条记忆。")
        else:
            print(record.model_dump_json(indent=2))
        return
    if len(parts) == 3 and parts[1] == "history":
        results = await retriever.service.search(
            MemoryQuery(
                text=parts[2],
                limit=20,
                statuses=[MemoryStatus.COLD, MemoryStatus.ARCHIVED, MemoryStatus.SUPERSEDED],
            )
        )
        if not results:
            print("朝汐 > 没有找到相关历史记忆。")
            return
        for item in results:
            record = item.record
            print(f"{record.id} [{record.status.value}] {record.updated_at.isoformat()} {record.content}")
        return
    print(
        "用法：/memory search <关键词>、/memory history <关键词>、"
        "/memory get <memory_id> 或 /memory maintain"
    )


async def handle_planner_command(agent: ZhaoxiAgent, text: str) -> None:
    """Start, inspect, resume, cancel, and trace in-memory planned tasks."""
    planner = agent.planner
    if planner is None:
        print("朝汐 > Planner 未启用。")
        return
    command, _, remainder = text.partition(" ")
    remainder = remainder.strip()
    if command == "/plan" and remainder:
        response = await planner.run(remainder)
        print(f"朝汐 > [{response.goal_id}] {response.content}")
        return
    if command == "/plan":
        goals = await planner.store.list()
        if not goals:
            print("朝汐 > 当前没有规划任务。")
            return
        for goal in goals:
            print(f"{goal.id} [{goal.status.value}] {goal.description}")
        return
    if command == "/resume":
        goal_id, separator, answer = remainder.partition(" ")
        if not separator or not answer.strip():
            print("用法：/resume <goal_id> <补充信息>")
            return
        response = await planner.resume(goal_id, answer.strip())
        print(f"朝汐 > [{response.goal_id}] {response.content}")
        return
    if command == "/cancel" and remainder:
        goal = await planner.cancel(remainder)
        print(f"朝汐 > 任务 {goal.id} 当前状态：{goal.status.value}")
        return
    if command == "/trace" and remainder:
        events = planner.trace.events(remainder)
        if not events:
            print("朝汐 > 没有找到该任务的执行轨迹。")
            return
        for event in events:
            print(f"{event.timestamp.isoformat()} {event.event_type} step={event.step_id or '-'}")
        return
    print("用法：/plan <目标>、/plan、/resume <goal_id> <补充信息>、/cancel <goal_id>、/trace <goal_id>")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="zhaoxi")
    parser.add_argument("--web", action="store_true", help="启动本地 Web 交互界面")
    parser.add_argument("--desktop", action="store_true", help="启动本地桌面常驻界面")
    args = parser.parse_args()
    if args.desktop:
        from zhaoxi.desktop import run_desktop

        run_desktop()
        return
    if args.web:
        from zhaoxi.web import run_web

        run_web()
        return
    asyncio.run(interactive())


async def handle_proactive_command(agent: ZhaoxiAgent, text: str) -> None:
    runtime = agent.proactive
    scheduler = agent.proactive_scheduler
    state = agent.proactive_state
    if runtime is None or scheduler is None or state is None:
        print("朝汐 > Proactive Agent 未启用。")
        return
    parts = text.split(maxsplit=3)
    command = parts[1] if len(parts) > 1 else "status"
    if command == "status":
        quiet = state.quiet_until.isoformat() if state.quiet_until else "off"
        print(f"朝汐 > proactive={'on' if state.enabled else 'off'} quiet={quiet}")
        return
    if command in {"on", "off"}:
        state.enabled = command == "on"
        print(f"朝汐 > 主动能力已{('开启' if state.enabled else '关闭')}。")
        return
    if command == "quiet":
        if len(parts) > 2 and parts[2] == "off":
            state.quiet_until = None
        else:
            minutes = int(parts[2]) if len(parts) > 2 else 60
            state.quiet_until = datetime.now(UTC) + timedelta(minutes=minutes)
        print("朝汐 > Quiet Mode 已更新。")
        return
    if command == "remind" and len(parts) == 4:
        minutes = int(parts[2])
        if minutes < 1 or minutes > 525600:
            raise ValueError("提醒分钟数必须在 1 到 525600 之间")
        schedule = Schedule(
            event_type="reminder.due",
            kind=ScheduleKind.ONCE,
            next_fire_at=datetime.now(UTC) + timedelta(minutes=minutes),
            payload={"text": parts[3]},
        )
        await runtime.store.save_schedule(schedule)
        print(f"朝汐 > 已创建提醒 {schedule.schedule_id}。")
        return
    if command == "tick":
        events = await scheduler.tick()
        for event in events:
            await runtime.process(event, datetime.now(UTC), state)
        print(f"朝汐 > 已处理 {len(events)} 个到期事件。")
        return
    if command == "schedules":
        for item in await runtime.store.list_schedules():
            print(f"{item.schedule_id} [{'on' if item.enabled else 'off'}] {item.next_fire_at.isoformat()} {item.event_type}")
        return
    if command in {"inbox", "history"}:
        items = await runtime.store.list_deliveries()
        for item in items:
            print(f"{item.delivery_id} [{item.status.value}] {item.content} reason={item.decision_reason}")
        return
    print("用法：/proactive [status|on|off|quiet [分钟|off]|remind <分钟> <内容>|tick|schedules|inbox|history]")


async def handle_permission_command(agent: ZhaoxiAgent, text: str) -> None:
    """Inspect and resolve the shared Agent/Planner permission gateway."""
    command, _, value = text.partition(" ")
    value = value.strip()
    gateway = agent.tool_executor.gateway
    if command == "/permissions":
        items = [item for item in gateway.store.pending.values() if not item.resolved]
        if not items:
            print("朝汐 > 当前没有待确认操作。")
            return
        for item in items:
            print(
                f"{item.confirmation_id} [{item.request.permission.value}] "
                f"{item.request.action_summary} scope={item.request.resource_scope}"
            )
        return
    if command == "/approve" and value:
        if value in agent._pending_permissions:
            response = await agent.approve_permission(value)
        elif agent.planner and value in agent.planner._pending_permissions:
            response = await agent.planner.approve_permission(value)
        else:
            gateway.approve(value)
            print("朝汐 > 已批准该操作；等待对应任务恢复。")
            return
        print(f"朝汐 > {response.content}")
        return
    if command == "/deny" and value:
        if value in agent._pending_permissions:
            response = await agent.deny_permission(value)
        elif agent.planner and value in agent.planner._pending_permissions:
            response = await agent.planner.deny_permission(value)
        else:
            gateway.deny(value)
            print("朝汐 > 已拒绝该操作。")
            return
        print(f"朝汐 > {response.content}")
        return
    if command == "/revoke" and value:
        gateway.revoke(value)
        print("朝汐 > 已撤销该授权。")
        return
    if command == "/audit":
        limit = int(value) if value.isdigit() else 20
        events = (
            gateway.audit.read(limit)
            if hasattr(gateway.audit, "read")
            else getattr(gateway.audit, "events", [])[-limit:]
        )
        if not events:
            print(f"朝汐 > 审计记录保存在 {getattr(gateway.audit, 'path', '配置的审计存储')}。")
            return
        for event in events:
            print(f"{event.timestamp.isoformat()} {event.event_type} {event.tool_name}")
        return
    print("用法：/permissions、/approve <id>、/deny <id>、/revoke <grant_id>、/audit [limit]")
