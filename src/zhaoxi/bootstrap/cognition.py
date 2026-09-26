"""ZhaoXi cognition composition."""

from zhaoxi.config.settings import Settings
from zhaoxi.core.context import ContextBuilder
from zhaoxi.personality.loader import CanineExpressionLoader, ExpressionLoader, FewShotDialoguesLoader, PersonalityLoader
from zhaoxi.planner.runtime import PlannerRuntime
from zhaoxi.planner.sqlite import SQLitePlanStore
from zhaoxi.planner.trace import TraceRecorder
from zhaoxi.workflow.loader import WorkflowLoader
from zhaoxi.workflow.registry import WorkflowRegistry
from zhaoxi.workflow.runtime import WorkflowRuntime
from zhaoxi.workflow.sqlite import SQLiteWorkflowStore


def build_cognition_runtime(settings: Settings, memory_retriever, emoji_service, agenda_service, current_cognition_service, session_store, session_record, provider, registry, conversation, tool_executor, tool_packages, package_capabilities, tool_package_errors):
    context_builder = ContextBuilder(
        PersonalityLoader.load_prompt(), memory_retriever=memory_retriever, timezone=settings.proactive_timezone,
        expression_prompt="\n\n".join((
            ExpressionLoader.load_prompt(),
            CanineExpressionLoader.load_prompt(),
            FewShotDialoguesLoader.load_prompt(),
        )),
        character_components=[
            ("system.personality", PersonalityLoader.load_prompt()),
            ("system.expression", ExpressionLoader.load_prompt()),
            ("system.canine_expression", CanineExpressionLoader.load_prompt()),
            ("system.few_shot_dialogues", FewShotDialoguesLoader.load_prompt()),
        ],
        emoji_service=emoji_service,
        agenda_service=agenda_service,
        current_cognition_service=current_cognition_service,
        agenda_context_enabled=settings.agenda_context_enabled,
        image_thumbnail_cache=session_store.thumbnail_cache(session_record.id),
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
    registered_workflows = []
    if settings.workflow_enabled:
        workflow_registry = WorkflowRegistry(registry)
        for definition in WorkflowLoader().load_directory(settings.workflow_directory):
            workflow_registry.register(definition)
        for package in tool_packages:
            if package_capabilities[package.package_id]["workflow"]:
                try:
                    for workflow_path in package.workflow_paths():
                        for definition in WorkflowLoader().load_directory(workflow_path):
                            workflow_registry.register(definition)
                except Exception as exc:
                    tool_package_errors.append({"source": f"{package.package_id}:workflow", "error": type(exc).__name__})
        workflow = WorkflowRuntime(
            workflow_registry,
            tool_executor,
            SQLiteWorkflowStore(settings.workflow_db_path),
            max_steps=settings.workflow_max_steps,
            max_events=settings.workflow_max_events,
        )
        registered_workflows = workflow_registry.list()
    return context_builder, planner, workflow, registered_workflows
