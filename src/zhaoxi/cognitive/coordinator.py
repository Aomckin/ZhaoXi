"""Natural-language entrypoint integrating routing, execution, and memory."""

import logging
from dataclasses import dataclass

from zhaoxi.cognitive.memory_decision import AutoMemory, MemoryAction
from zhaoxi.cognitive.router import CognitiveRoute, CognitiveRouter, RouteDecision
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.observability import current_trace
from zhaoxi.permission.models import PendingConfirmation
from zhaoxi.reliability.retry import budget_stage_scope
from zhaoxi.workflow.runtime import WorkflowRuntimeError

logger = logging.getLogger("COGNITIVE")


@dataclass(slots=True)
class CognitiveResponse:
    content: str
    route: CognitiveRoute
    goal_id: str | None = None
    memory_action: MemoryAction = MemoryAction.IGNORE
    permission_confirmation: PendingConfirmation | None = None
    workflow_run_id: str | None = None


class CognitiveCoordinator:
    """Keep input routing separate from post-response memory organization."""

    def __init__(
        self,
        *,
        agent: ZhaoxiAgent,
        router: CognitiveRouter,
        auto_memory: AutoMemory | None = None,
    ) -> None:
        self.agent = agent
        self.router = router
        self.auto_memory = auto_memory

    async def run(self, user_message: str, *, images: list[str] | None = None) -> CognitiveResponse:
        # The text-only router cannot interpret attachments. Use the existing
        # tool-capable loop so the main model sees the image and retains tools.
        trace = current_trace()
        decision_service = getattr(self.agent, "decision_service", None)
        if decision_service is not None and not images and decision_service.is_override(user_message):
            decision_service.accept_override(user_message)
            reply = await self.agent.run_decision_override_reply(user_message)
            return CognitiveResponse(content=reply.content, route=CognitiveRoute.DIRECT)
        if images:
            decision = RouteDecision(route=CognitiveRoute.TOOL, reason="image input")
            if trace:
                trace.emit("input_images_received", "input", "success", "已读取图片", metadata={"image_count": len(images)})
        else:
            if trace:
                trace.emit("model_step_started", "routing", "running", "正在理解请求…", step_id=0)
            with budget_stage_scope("understanding"):
                decision = await self.router.route(user_message, recent_context=self._recent_routing_context())
            if trace and not getattr(self.router, "last_provider_failed", False):
                trace.emit("model_step_finished", "routing", "success", "已确定处理方式", step_id=0)
        logger.info(
            "route=%s requires_tool_call=%s required_tool=%s workflow_selected=%s available_tools=%s reason=%s",
            decision.route.value,
            decision.requires_tool_call,
            decision.required_tool,
            bool(decision.workflow_id),
            getattr(self.router, "available_tool_names", []),
            decision.reason[:160],
        )
        if decision_service is not None and not images:
            planner_requested = (decision.route == CognitiveRoute.PLAN and
                                 any(marker in user_message for marker in ("还是", "或者", "选", "方向")))
            result = await decision_service.evaluate(user_message, planner_requested=planner_requested)
            if result is not None:
                reply = await self.agent.run_decision_reply(
                    user_message, result,
                    mode=decision_service.last_context.decision_mode if decision_service.last_context else "normal",
                )
                content = reply.content
                return CognitiveResponse(content=content, route=CognitiveRoute.DIRECT)
        workflow_run_id = None
        if decision.route == CognitiveRoute.WORKFLOW and self.agent.workflow is not None and decision.workflow_id:
            self.agent.conversation.add_user(user_message.strip())
            try:
                workflow_run = await self.agent.workflow.start(
                    decision.workflow_id,
                    decision.workflow_inputs,
                    user_intent=user_message,
                )
                workflow_run_id = workflow_run.id
                result = await self.agent.finalize_workflow(workflow_run)
            except WorkflowRuntimeError as exc:
                logger.warning("workflow rejected trace_id=%s error=%s", exc.trace_id, str(exc))
                result = self.agent._workflow_response_error(exc.user_message, exc.trace_id)
                self.agent.conversation.add_assistant(result.content)
            content = result.content
            goal_id = None
        elif decision.route == CognitiveRoute.PLAN and self.agent.planner is not None:
            result = await self.agent.run_planned(user_message)
            content = result.content
            goal_id = result.goal_id
        elif decision.route == CognitiveRoute.DIRECT:
            result = await self.agent.run_direct(user_message)
            if result.used_tool_path:
                decision.route = CognitiveRoute.TOOL
            content = result.content
            goal_id = None
        else:
            if decision.route == CognitiveRoute.PLAN:
                decision.route = CognitiveRoute.TOOL
            result = await self.agent.run(
                user_message, require_tool_call=decision.requires_tool_call,
                required_tool=decision.required_tool,
                **({"images": images} if images else {})
            )
            content = result.content
            goal_id = None
        memory_action = MemoryAction.IGNORE
        if self.auto_memory is not None:
            if trace:
                trace.emit("memory_maintenance_started", "memory", "running", "正在整理相关记忆…")
            try:
                with budget_stage_scope("finalization"):
                    memory_decision = await self.auto_memory.process(user_message, content)
                memory_action = memory_decision.action
                logger.info("auto_memory action=%s", memory_action.value)
                if trace:
                    trace.emit("memory_maintenance_finished", "memory", "success", "记忆整理已完成")
            except Exception as exc:
                if trace:
                    trace.emit("memory_maintenance_failed", "memory", "warning", "记忆整理未完成",
                               error_code="memory_maintenance_error", metadata={"error_type": type(exc).__name__})
                logger.warning("auto memory failed; preserving response: %s", exc)
        return CognitiveResponse(
            content=content,
            route=decision.route,
            goal_id=goal_id,
            memory_action=memory_action,
            permission_confirmation=getattr(result, "permission_confirmation", None),
            workflow_run_id=workflow_run_id,
        )

    def _recent_routing_context(self, limit: int = 6, max_chars: int = 2400) -> str:
        """Provide bounded dialogue context to the router without Tool observations or metadata."""
        lines = []
        for message in self.agent.conversation.recent(limit):
            if message.role.value not in {"user", "assistant"} or not message.content:
                continue
            lines.append(f"{message.role.value}: {message.content[:600]}")
        return "\n".join(lines)[-max_chars:]
