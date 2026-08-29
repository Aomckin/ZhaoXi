"""Thin interactive command-line interface."""

import asyncio

from zhaoxi.config.logging import configure_logging
from zhaoxi.config.settings import Settings
from zhaoxi.cognitive.coordinator import CognitiveCoordinator
from zhaoxi.cognitive.memory_decision import AutoMemory
from zhaoxi.cognitive.router import CognitiveRouter
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.errors import ZhaoxiError
from zhaoxi.models.openai_compatible import OpenAICompatibleProvider
from zhaoxi.memory.models import MemoryQuery, MemoryStatus
from zhaoxi.memory.lifecycle import MemoryLifecyclePolicy
from zhaoxi.memory.retrieval import MemoryRetriever
from zhaoxi.memory.service import MemoryService
from zhaoxi.memory.sqlite import SQLiteMemoryRepository
from zhaoxi.personality.loader import PersonalityLoader
from zhaoxi.planner.runtime import PlannerRuntime
from zhaoxi.planner.store import InMemoryPlanStore
from zhaoxi.planner.trace import TraceRecorder
from zhaoxi.permission.audit import JsonlAuditSink
from zhaoxi.permission.executor import ToolExecutor
from zhaoxi.permission.gateway import PermissionGateway
from zhaoxi.permission.models import PermissionLevel, PermissionStatus
from zhaoxi.permission.policy import DefaultPermissionPolicy
from zhaoxi.tools.builtin import create_builtin_tools
from zhaoxi.tools.registry import ToolRegistry


def build_agent(settings: Settings) -> ZhaoxiAgent:
    """Wire v0.2 dependencies at the application boundary."""
    settings.validate_model_config()
    provider = OpenAICompatibleProvider(
        base_url=settings.model_base_url,
        api_key=settings.model_api_key,
        model=settings.model_name,
        timeout=settings.request_timeout_seconds,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
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
        audit=JsonlAuditSink(settings.permission_audit_path),
        confirmation_ttl_seconds=settings.permission_confirmation_ttl_seconds,
    )
    tool_executor = ToolExecutor(
        registry,
        gateway,
        max_output_chars=settings.permission_max_tool_output_chars,
    )
    conversation = Conversation(max_messages=settings.max_context_messages)
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
            store=InMemoryPlanStore(),
            trace=TraceRecorder(settings.planner_trace_max_events),
            max_steps=settings.planner_max_steps,
            max_replans=settings.planner_max_replans,
            max_attempts_per_step=settings.planner_max_attempts_per_step,
            step_timeout_seconds=settings.planner_step_timeout_seconds,
            total_timeout_seconds=settings.planner_total_timeout_seconds,
            tool_executor=tool_executor,
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
    )
    if settings.cognitive_router_enabled:
        agent.cognitive = CognitiveCoordinator(
            agent=agent,
            router=CognitiveRouter(provider),
            auto_memory=AutoMemory(provider, memory_service) if settings.auto_memory_enabled else None,
        )
    return agent


async def interactive() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    try:
        agent = build_agent(settings)
    except ZhaoxiError as exc:
        print(f"配置错误：{exc}")
        return

    print(
        "Zhaoxi v0.4 · Permission\n"
        "输入 /plan <目标> 执行规划任务，/permissions 查看权限，/tools 查看工具，/exit 退出。"
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
            print("朝汐 > 当前会话已清空。")
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
        try:
            response = await agent.run_natural(text)
            print(f"朝汐 > {response.content}")
        except ZhaoxiError as exc:
            print(f"朝汐 > 这次没有顺利完成：{exc}")
        except Exception:
            import logging

            logging.getLogger("ERROR").exception("unexpected CLI failure")
            print("朝汐 > 遇到了未预期的内部错误，请查看日志。")


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
    asyncio.run(interactive())


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
