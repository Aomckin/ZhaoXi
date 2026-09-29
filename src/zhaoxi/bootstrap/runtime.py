"""ZhaoXi runtime composition."""

from pathlib import Path
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
    )
    agent.settings = settings
    agent.experience_stream = ExperienceStream(Path(".zhaoxi") / "experience.db")
    agent.experience_stream.clear_expired()
    agent.cognitive_ingress = CognitiveIngress(agent.experience_stream)
    if planner is not None:
        planner.cognitive_ingress = agent.cognitive_ingress
        from zhaoxi.cognitive_stream.turn import current_turn
        planner.current_trigger_provider = lambda: (current_turn().trigger_event if current_turn() else None)
    agent.attention_retriever = AttentionRetriever(agent.experience_stream)
    agent.session_projector = SessionProjector(agent.experience_stream)
    context_builder.attention_retriever = agent.attention_retriever
    agent.session_store = session_store
    agent.session_record = session_record
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
    agent.reflection = reflection_service
    agent.reflection_periods = reflection_periods
    agent.archive = archive_service
    agent.agenda = agenda_service
    agent.current_cognition = current_cognition_service
    from zhaoxi.decision import DecisionService
    agent.decision_service = DecisionService(
        provider,
        rule_directory=Path(__file__).resolve().parents[3] / "data" / "decisions" / "rules",
        data_directory=Path(".zhaoxi") / "decisions",
        agenda=agenda_service,
        current_cognition=current_cognition_service,
        memory_retriever=context_builder.memory_retriever,
        tool_catalog=registry.manifest(),
        timezone=settings.proactive_timezone,
    )
    agent.decision_service.attention_retriever = agent.attention_retriever
    agent.current_cognition_maintainer = CurrentCognitionMaintainer(
        current_cognition_service, provider, timezone=settings.proactive_timezone,
    )
    agent.emoji_service = emoji_service
    agent.emoji_manager = emoji_manager
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
    agent.backup_manager = BackupManager(
        settings.backup_directory,
        data_stores,
        retention_count=settings.backup_retention_count,
    )
    agent.memory_service = memory_service
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
        routing_hints = []
        for package in tool_packages:
            if not package_capabilities[package.package_id]["router_hints"]:
                continue
            try:
                routing_hints.extend(package.routing_hints())
            except Exception as exc:
                tool_package_errors.append({"source": f"{package.package_id}:router_hints", "error": type(exc).__name__})
        agent.cognitive = CognitiveCoordinator(
            agent=agent,
            router=CognitiveRouter(
                provider,
                routing_hints=routing_hints,
                tool_catalog=registry.manifest(),
                archive_enabled=archive_service is not None,
            ),
            fast_gate=(FastDialogueGate() if settings.fast_dialogue_enabled else None),
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
    agent.internal_activity = InternalActivityRuntime(agent, settings, settings.internal_activity_db_path)
    if getattr(agent, "proactive_worker", None) is not None:
        agent.internal_activity.proactive_check = agent.proactive_worker.tick
        agent.proactive_worker.activity = agent.internal_activity
    return agent
