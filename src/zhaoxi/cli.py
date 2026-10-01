"""Thin interactive command-line interface."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zhaoxi.config.logging import configure_logging
from zhaoxi.config.settings import Settings
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.errors import ZhaoxiError
from zhaoxi.memory.models import MemoryQuery, MemoryStatus
from zhaoxi.proactive import Schedule, ScheduleKind
from zhaoxi.reliability import provider_budget_scope, startup_diagnostics
from zhaoxi.reflection.models import ReflectionKind
from zhaoxi.bootstrap.runtime import build_agent
from zhaoxi.bootstrap.knowledge import build_archive


async def interactive() -> None:
    settings = Settings()
    configure_logging(
        settings.log_level,
        path=settings.log_path,
        max_bytes=settings.log_max_bytes,
        backup_count=settings.log_backup_count,
    )
    try:
        agent = build_agent(settings)
    except ZhaoxiError as exc:
        print(f"配置错误：{exc}")
        return

    from zhaoxi.interfaces import InterfaceGateway, UnifiedMessage, InterfaceChannel
    interface = InterfaceGateway(agent)
    print(
        f"Zhaoxi v{__import__('zhaoxi').__version__}\n"
        "输入 /diagnostics 检查运行状态，/capabilities 查看能力，"
        "/reflection 生成回顾，/exit 退出。"
    )
    while True:
        try:
            text = input("\nYou > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n朝汐 > 再见，暗苟。")
            registry = getattr(agent, "registry", None)
            if registry is not None:
                registry.close_providers()
            return
        if not text:
            continue
        if text == "/exit":
            print("朝汐 > 再见，暗苟。")
            registry = getattr(agent, "registry", None)
            if registry is not None:
                registry.close_providers()
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
        if text == "/capabilities":
            print(agent.capability_catalog)
            continue
        if text == "/reflections":
            if agent.reflection is None:
                print("朝汐 > Reflection 未启用。")
                continue
            records = await agent.reflection.repository.list(20)
            if not records:
                print("朝汐 > 暂无回顾记录。")
            for record in records:
                print(
                    f"{record.kind.value} {record.period.label} "
                    f"[{record.status.value}] r{record.revision} · {record.summary}"
                )
            continue
        if text.startswith("/reflection"):
            parts = text.split()
            if len(parts) < 2 or parts[1] not in {"daily", "weekly", "monthly", "seasonal"}:
                print("朝汐 > 用法：/reflection <daily|weekly|monthly|seasonal> [--regenerate]")
                continue
            if agent.reflection is None or agent.reflection_periods is None:
                print("朝汐 > Reflection 未启用。")
                continue
            kind = ReflectionKind(parts[1])
            try:
                with provider_budget_scope(
                    settings.request_max_model_calls,
                    settings.request_max_total_tokens,
                ):
                    record = await agent.reflection.generate(
                        kind,
                        agent.reflection_periods.resolve(kind),
                        regenerate="--regenerate" in parts[2:],
                    )
                print(f"朝汐 > {record.summary}")
                for section in record.sections:
                    print(f"\n{section.name}")
                    for point in section.points:
                        print(f"- {point.text}")
                for uncertainty in record.uncertainties:
                    print(f"- 待确认：{uncertainty}")
            except Exception as exc:
                logging.getLogger("REFLECTION").warning(
                    "reflection generation failed type=%s", type(exc).__name__
                )
                print("朝汐 > 回顾生成失败，请稍后重试或检查数据来源。")
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
            response = await interface.chat(UnifiedMessage(channel=InterfaceChannel.CLI, content=text))
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
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--web", action="store_true", help="启动本地 Web 交互界面")
    modes.add_argument("--desktop", action="store_true", help="启动本地桌面常驻界面")
    modes.add_argument("--doctor", action="store_true", help="检查首次启动配置与可选能力，不启动 Agent")
    modes.add_argument("--archive-status", action="store_true", help="查看潮庭书库索引状态，不启动 Agent")
    modes.add_argument("--reindex-archive", action="store_true", help="重建潮庭书库索引，不启动 Agent")
    from zhaoxi.memory.migration import ACTIONS
    modes.add_argument("--memory-maintenance", choices=("audit",*ACTIONS), help="离线记忆体检/迁移，默认dry-run")
    modes.add_argument("--rollback-memory", metavar="BACKUP", help="从记忆快照回滚（须停机）")
    modes.add_argument("--media-migrate", choices=("experience","perception","session"), help="离线图片迁移，默认dry-run")
    modes.add_argument("--vacuum-session", action="store_true", help="离线释放Session freelist")
    parser.add_argument("--apply", action="store_true", help="实际写入；默认只读dry-run")
    parser.add_argument("--offline", action="store_true", help="确认运行时已停止，允许离线写入")
    parser.add_argument("--output-dir", help="迁移报告/备份目录")
    parser.add_argument("--embedding-snapshot", help="Reuse compatible content-hash-matching vectors from a local snapshot")
    parser.add_argument("--cancel-file", help="出现此文件时取消迁移，保留原库")
    parser.add_argument("--background", action="store_true", help="Desktop 初始隐藏窗口")
    for action in ("install", "remove"):
        modes.add_argument(f"--{action}-autostart", action="store_true")
    modes.add_argument("--autostart-status", action="store_true")
    args = parser.parse_args()
    if args.apply and not (args.memory_maintenance or args.media_migrate or args.vacuum_session or args.rollback_memory):
        parser.error("--apply requires a maintenance action")
    if (args.apply or args.rollback_memory) and not args.offline:
        parser.error("writes require --offline with the runtime stopped")
    if args.memory_maintenance or args.media_migrate or args.vacuum_session or args.rollback_memory:
        import json
        from zhaoxi.memory.migration import audit, migrate, restore
        from zhaoxi.memory.embedding import provider_from_settings
        from zhaoxi.reliability.media import migrate_inline_media, database_metrics, vacuum_database
        configured=Settings()
        cancel=lambda: bool(args.cancel_file and Path(args.cancel_file).exists())
        progress=lambda value: print(json.dumps({"progress":value},ensure_ascii=False),file=__import__('sys').stderr)
        if args.rollback_memory:
            payload=restore(args.rollback_memory,configured.memory_db_path)
        elif args.memory_maintenance == "audit":
            payload=audit(configured.memory_db_path)
        elif args.memory_maintenance:
            provider=provider_from_settings(configured)
            payload=asyncio.run(migrate(configured.memory_db_path,action=args.memory_maintenance,
                dry_run=not args.apply,output_dir=args.output_dir,embedding_provider=provider,
                cluster_max_members=configured.memory_cluster_max_members,cancel=cancel,progress=progress,embedding_snapshot=args.embedding_snapshot))
        elif args.media_migrate:
            db_path=str(Path(configured.memory_db_path).parent/'experience.db') if args.media_migrate=='experience' else getattr(configured,args.media_migrate+'_db_path')
            payload=migrate_inline_media(db_path,dry_run=not args.apply,output_dir=args.output_dir,cancel=cancel,progress=progress,media_directory=configured.media_directory)
        else:
            payload=vacuum_database(configured.session_db_path) if args.apply else database_metrics(configured.session_db_path)
        print(json.dumps(payload,ensure_ascii=False,indent=2))
        return
    if args.background and not args.desktop:
        parser.error("--background 必须与 --desktop 一起使用")
    if args.install_autostart or args.remove_autostart or args.autostart_status:
        import json
        from zhaoxi.desktop.autostart import manage_autostart

        action = "install" if args.install_autostart else "remove" if args.remove_autostart else "status"
        try:
            print(json.dumps(manage_autostart(action), ensure_ascii=False, indent=2))
        except RuntimeError as exc:
            parser.exit(1, f"自启动操作失败：{exc}\n")
        return
    if args.doctor:
        import json

        print(json.dumps(startup_diagnostics(Settings()), ensure_ascii=False, indent=2))
        return
    if args.archive_status or args.reindex_archive:
        import json

        configured = Settings()
        archive = build_archive(configured, reindex=False)
        if archive is None:
            payload = {"enabled": False}
        elif args.reindex_archive:
            payload = archive.reindex(force=True).model_dump(mode="json")
        else:
            payload = archive.status()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if args.desktop:
        from zhaoxi.desktop import run_desktop

        run_desktop(background=args.background)
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
