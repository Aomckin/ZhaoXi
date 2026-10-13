"""ZhaoXi runtime composition."""

from pathlib import Path
import sqlite3
from zhaoxi.config.settings import Settings
from zhaoxi.cognitive_stream import ExperienceStream, CognitiveIngress, AttentionRetriever, SessionProjector
from zhaoxi.cognitive.coordinator import CognitiveCoordinator
from zhaoxi.cognitive.fast_gate import FastDialogueGate
from zhaoxi.cognitive.memory_decision import AutoMemory
from zhaoxi.memory.consolidation import AutoConsolidationConfig
from zhaoxi.cognitive.router import CognitiveRouter
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.fast_chat import FastChatRuntime
from zhaoxi.errors import ConfigError
from zhaoxi.permission.models import InvocationOrigin
from zhaoxi.current_cognition import CurrentCognitionMaintainer
from zhaoxi.internal_activity import InternalActivityRuntime
from zhaoxi.reliability import BackupManager
from zhaoxi.bootstrap.models import build_model_runtime
from zhaoxi.bootstrap.knowledge import build_knowledge_runtime, build_reflection_runtime
from zhaoxi.bootstrap.tools import build_tool_runtime
from zhaoxi.bootstrap.storage import build_storage_runtime, build_data_store_specs
from zhaoxi.bootstrap.cognition import build_cognition_runtime
from zhaoxi.bootstrap.proactive import build_proactive_runtime, attach_proactive_runtime


def build_agent(settings: Settings) -> ZhaoxiAgent:
    """Assemble the current application runtime at one boundary."""
    provider = build_model_runtime(settings)
    memory_service, memory_retriever, agenda_service, current_cognition_service, archive_service = build_knowledge_runtime(settings)
    emoji_service, emoji_manager, registry, tool_packages, package_records, package_capabilities, tool_package_errors = build_tool_runtime(settings, memory_service, archive_service, agenda_service)
    reflection_service, reflection_periods = build_reflection_runtime(settings, memory_service, tool_packages, package_capabilities, tool_package_errors, provider)
    gateway, tool_executor, session_store, session_record, conversation = build_storage_runtime(settings, registry, emoji_manager)
    context_builder, planner, workflow, registered_workflows = build_cognition_runtime(settings, memory_retriever, emoji_service, agenda_service, current_cognition_service, session_store, session_record, provider, registry, conversation, tool_executor, tool_packages, package_capabilities, tool_package_errors)
    proactive, proactive_scheduler, proactive_state = build_proactive_runtime(settings, context_builder)
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
        tool_router_mode=settings.tool_router_mode,
        decision_mode=settings.decision_mode,
    )
    runtime = agent.runtime
    runtime.settings = settings
    runtime.experience_stream = ExperienceStream(settings.experience_db_path, media_directory=settings.media_directory)
    agent.experience_stream.clear_expired()
    from zhaoxi.tools.builtin.social_context import ReadSocialContextTool
    registry.register(ReadSocialContextTool(agent.experience_stream,perception_path=settings.perception_db_path,max_output_chars=min(8000,settings.permission_max_tool_output_chars)))
    runtime.cognitive_ingress = CognitiveIngress(agent.experience_stream)
    if planner is not None:
        planner.cognitive_ingress = agent.cognitive_ingress
        from zhaoxi.cognitive_stream.turn import current_turn
        planner.current_trigger_provider = lambda: (current_turn().trigger_event if current_turn() else None)
    runtime.attention_retriever = AttentionRetriever(agent.experience_stream)
    runtime.session_projector = SessionProjector(agent.experience_stream)
    context_builder.attention_retriever = agent.attention_retriever
    runtime.session_store = session_store
    runtime.session_record = session_record
    if settings.perception_enabled:
        import json
        from zhaoxi.perception.ledger import InteractionLedger
        shared_ledger = InteractionLedger(settings.perception_db_path,
                                          settings.interaction_ledger_ttl_hours)
        def shared_self_context():
            state = json.dumps(shared_ledger.runtime_state(), ensure_ascii=False)
            return "[Runtime Self State]\n" + state + "\n[/Runtime Self State]"
        context_builder.self_activity_provider = shared_self_context
    agent.tool_packages = package_records
    agent.tool_package_instances = {package.package_id: package for package in tool_packages}
    agent.tool_package_errors = tool_package_errors
    runtime.reflection = reflection_service
    runtime.reflection_periods = reflection_periods
    runtime.archive = archive_service
    runtime.agenda = agenda_service
    runtime.current_cognition = current_cognition_service
    from zhaoxi.decision import DecisionService
    runtime.decision_service = DecisionService(
        provider,
        rule_directory=Path(__file__).resolve().parents[3] / "data" / "decisions" / "rules",
        data_directory=settings.decision_data_directory,
        agenda=agenda_service,
        current_cognition=current_cognition_service,
        memory_retriever=context_builder.memory_retriever,
        tool_catalog=registry.manifest(),
        timezone=settings.proactive_timezone,
    )
    agent.decision_service.attention_retriever = agent.attention_retriever
    from zhaoxi.decision.history import ChoiceHistory
    awareness = agent.decision_awareness
    awareness.history = ChoiceHistory(settings.decision_data_directory)
    awareness.principles = agent.decision_service.rules
    awareness.agenda = agenda_service
    awareness.cognition = current_cognition_service
    awareness.memory = memory_retriever
    if settings.decision_learning_enabled and settings.decision_mode == "agency":
        from zhaoxi.decision.journal import DecisionJournalStore
        from zhaoxi.decision.user_principles import UserPrincipleStore, DecisionPrincipleArchiveProvider
        from zhaoxi.decision.learning import DecisionLearning
        awareness.principle_archive = DecisionPrincipleArchiveProvider(settings.archive_directory, settings.decision_principle_archive_paths)
        awareness.user_principles = UserPrincipleStore(settings.decision_user_principles_directory, awareness.principle_archive)
        awareness.user_principles.synchronize()
        from zhaoxi.decision.principle_tools import WriteUserPrinciple
        registry.register(WriteUserPrinciple(awareness))
        awareness.journal = DecisionJournalStore(settings.decision_data_directory)
        runtime.decision_learning = DecisionLearning(awareness.history, awareness.journal, awareness.user_principles, provider)
        from zhaoxi.decision.follow_up import DecisionFollowUp
        runtime.decision_follow_up = DecisionFollowUp(awareness.history, settings)
        awareness.follow_up = agent.decision_follow_up
    runtime.current_cognition_maintainer = CurrentCognitionMaintainer(
        current_cognition_service, provider, timezone=settings.proactive_timezone,
    )
    runtime.emoji_service = emoji_service
    runtime.emoji_manager = emoji_manager
    agent.capability_catalog = {
        "status": "ready",
        "tools": [
            {"name": tool.name, "description": tool.description}
            for tool in registry.list()
        ],
        "workflows": [
            {"id": definition.id, "name": definition.name, "aliases": definition.aliases}
            for definition in registered_workflows
        ],
        "packages": [
            {
                **package.capabilities(),
                "enabled_capabilities": [
                    name for name, value in package_capabilities[package.package_id].items() if value
                ],
            }
            for package in tool_packages
            if hasattr(package, "capabilities")
        ],
        "examples": [
            "记住我偏好晚上进行深度开发。",
            "帮我分步骤准备明天下午的任务。",
            "提醒我 30 分钟后休息。",
            "生成今天的回顾。",
        ],
    }
    agent.metrics = provider.metrics
    if proactive is not None:
        from zhaoxi.cognitive_stream.models import CognitiveEventType
        def record_delivery(delivery):
            agent.cognitive_ingress.record(CognitiveEventType.PROACTIVE_EVENT,
                delivery.content or "", source="proactive", channel="desktop",
                session_id="local", source_refs=["proactive:" + delivery.delivery_id],
                metadata={"event_type": delivery.event_type})
        proactive.sink.on_delivered = record_delivery
    attach_proactive_runtime(agent, settings, proactive, proactive_scheduler, proactive_state, tool_packages, package_capabilities, tool_package_errors, provider, context_builder)
    data_stores = build_data_store_specs(settings, archive_enabled=archive_service is not None)
    runtime.backup_manager = BackupManager(
        settings.backup_directory,
        data_stores,
        retention_count=settings.backup_retention_count,
    )
    runtime.memory_service = memory_service
    # Ad-hoc Agent waits cannot safely reconstruct the exact provider tool-call
    # transcript after a crash. Fail them closed; Planner and Workflow waits
    # retain their own recoverable state.
    for confirmation_id, pending in list(gateway.store.pending.items()):
        if pending.resolved or pending.request.origin is not InvocationOrigin.AGENT:
            continue
        gateway.deny(confirmation_id)
    if settings.cognitive_router_enabled:
        routing_hints = []
        for package in tool_packages:
            if not package_capabilities[package.package_id]["router_hints"]:
                continue
            try:
                routing_hints.extend(package.routing_hints())
            except Exception as exc:
                tool_package_errors.append({"source": f"{package.package_id}:router_hints", "error": type(exc).__name__})
        runtime.cognitive = CognitiveCoordinator(
            agent=agent,
            router=CognitiveRouter(
                provider,
                routing_hints=routing_hints,
                tool_catalog=registry.manifest(),
                tool_catalog_provider=registry.manifest,
                workflow_catalog_provider=workflow.registry.catalog if workflow else None,
                archive_enabled=archive_service is not None,
                artifact_resolver=archive_service.artifact_reference_match if archive_service else None,
            ),
            fast_gate=(FastDialogueGate(settings.fast_gate, decision_mode=settings.decision_mode) if settings.fast_dialogue_enabled else None),
            fast_chat=(FastChatRuntime(
                agent, recent_limit=settings.fast_dialogue_recent_limit,
                max_chars=settings.fast_dialogue_context_max_chars,
            ) if settings.fast_dialogue_enabled else None),
            auto_memory=(AutoMemory(
                provider, memory_service,
                consolidation_config=AutoConsolidationConfig(
                    enabled=settings.memory_auto_consolidation_enabled,
                    after_episodes=settings.memory_consolidate_after_episodes,
                    interval_hours=settings.memory_consolidation_interval_hours,
                    min_evidence=settings.memory_consolidation_min_evidence,
                ),
            ) if settings.auto_memory_enabled else None),
        )
    try:
        runtime.internal_activity = InternalActivityRuntime(agent, settings, settings.internal_activity_db_path)
    except sqlite3.Error as exc:
        raise ConfigError(
            f"内部活动数据初始化失败（{type(exc).__name__}）。请检查数据库权限、锁定与完整性。"
        ) from exc
    # Open every active store before read-only health checks. SQLite must be
    # allowed to recover a hot rollback journal after an interrupted shutdown.
    unhealthy = [
        name for name, status in agent.backup_manager.health().items()
        if status["exists"] and not status["healthy"]
    ]
    if unhealthy:
        raise ConfigError(f"数据健康检查失败：{', '.join(unhealthy)}。请从已验证备份恢复。")
    if getattr(agent, "decision_follow_up", None):
        agent.decision_follow_up.runtime = agent.internal_activity
    if getattr(agent, "proactive_worker", None) is not None:
        agent.internal_activity.proactive_check = agent.proactive_worker.tick
        agent.proactive_worker.activity = agent.internal_activity
    return agent
