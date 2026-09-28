"""ZhaoXi proactive composition."""

from datetime import time
from zhaoxi.config.settings import Settings
from zhaoxi.proactive import InboxNotificationSink, InterruptPolicy, PolicyState, Priority, ProactiveRuntime, Scheduler, SQLiteProactiveStore, Subscription


def build_proactive_runtime(settings: Settings, context_builder):
    proactive = None
    proactive_scheduler = None
    proactive_state = PolicyState(enabled=settings.proactive_enabled)
    context_builder.interaction = proactive_state.interaction
    if settings.proactive_enabled:
        proactive_store = SQLiteProactiveStore(settings.proactive_db_path)
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
    return proactive, proactive_scheduler, proactive_state


def attach_proactive_runtime(agent, settings: Settings, proactive, proactive_scheduler, proactive_state, tool_packages, package_capabilities, tool_package_errors, provider, context_builder):
    if proactive is not None:
        from zhaoxi.proactive.heartbeat import TidalHeartbeat
        from zhaoxi.proactive.decision import ModelDecision
        from zhaoxi.proactive.worker import DecisionWorker
        sensors = []
        signal_providers = []
        for package in tool_packages:
            factory = getattr(package, "proactive_sensors", None)
            if package_capabilities[package.package_id]["proactive_provider"] and factory is not None:
                try:
                    sensors.extend(factory())
                except Exception as exc:
                    tool_package_errors.append({"source": f"{package.package_id}:proactive", "error": type(exc).__name__})
            signal_factory = getattr(package, "state_signal_providers", None)
            if package_capabilities[package.package_id]["state_signal_provider"] and signal_factory is not None:
                try:
                    signal_providers.extend(signal_factory())
                except Exception as exc:
                    tool_package_errors.append({"source": f"{package.package_id}:state_signals", "error": type(exc).__name__})
        agent.proactive_heartbeat = TidalHeartbeat(
            proactive, proactive_scheduler, proactive_state, settings, agent.metrics, sensors,
            signal_providers=signal_providers,
        )
        from zhaoxi.proactive.beat import ConversationBeatLoop
        agent.conversation_continuation = ConversationBeatLoop(
            settings, proactive_state.interaction, agent.conversation,
            pending_work=lambda: any(not p.resolved for p in agent.tool_executor.gateway.store.pending.values()),
        )
        agent.conversation_continuation.experience_stream = agent.experience_stream
        agent.proactive_heartbeat.continuation = agent.conversation_continuation
        decision = ModelDecision(provider, context_builder.character_prompt,
                                 agent.conversation, agent.conversation_continuation)
        decision.attention_retriever = getattr(agent, "attention_retriever", None)
        agent.proactive_worker = DecisionWorker(agent.proactive_heartbeat, decision)
