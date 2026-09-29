"""Natural-language entrypoint integrating routing, execution, and memory."""
from zhaoxi.cognitive_stream.turn import current_turn

import logging
from dataclasses import dataclass

from zhaoxi.cognitive.fast_gate import FastDialogueDecision, FastDialogueGate
from zhaoxi.cognitive.memory_decision import AutoMemory, MemoryAction
from zhaoxi.cognitive.router import CognitiveRoute, CognitiveRouter, RouteDecision
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.fast_chat import FastChatRuntime
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
        fast_gate: FastDialogueGate | None = None,
        fast_chat: FastChatRuntime | None = None,
    ) -> None:
        self.agent = agent
        self.router = router
        self.auto_memory = auto_memory
        self.fast_gate = fast_gate
        self.fast_chat = fast_chat or (FastChatRuntime(agent) if fast_gate is not None else None)
        self.force_fast_chat = False

    async def run(self, user_message: str, *, images: list[str] | None = None) -> CognitiveResponse:
        # The text-only router cannot interpret attachments. Use the existing
        # tool-capable loop so the main model sees the image and retains tools.
        trace = current_trace()
        decision_service = getattr(self.agent, "decision_service", None)
        if decision_service is not None and not images and decision_service.is_override(user_message):
            decision_service.accept_override(user_message)
            reply = await self.agent.run_decision_override_reply(user_message)
            return CognitiveResponse(content=reply.content, route=CognitiveRoute.DIRECT)
        decision = None
        result = None
        if not images and self.fast_gate is not None and self.fast_chat is not None:
            pending_permission = bool(self.agent._pending_permissions)
            gate = (FastDialogueDecision(True, "debug_force_fast")
                    if self.force_fast_chat and not pending_permission else self.fast_gate.decide(
                        user_message,
                        pending_permission=pending_permission,
                    ))
            if trace:
                trace.fast_gate_reason = gate.reason
                trace.emit("fast_gate_decided", "routing", "success", "已完成轻量通道判断",
                           metadata={"eligible": gate.eligible, "reason": gate.reason,
                                     "continuation_detected": gate.continuation_detected})
            if gate.eligible:
                fast_result = await self.fast_chat.run_fast_chat(
                    user_message, force=self.force_fast_chat,
                )
                if not fast_result.escalated:
                    result = fast_result
                    decision = RouteDecision(route=CognitiveRoute.FAST_CHAT, reason=gate.reason)
                    if trace:
                        trace.runtime_lane = "fast"
                        trace.route_source = "fast_gate"
                elif trace:
                    trace.escalation_reason = fast_result.escalation_reason
                    trace.route_source = "router_after_fast_escalation"
            else:
                decision = self._route_fast_exclusion(gate.reason, decision_service is not None)
                if decision is not None and trace:
                    trace.route_source = "fast_gate_exclusion"
        if decision is None:
            if images:
                decision = RouteDecision(route=CognitiveRoute.TOOL, reason="image input")
                if trace:
                    trace.route_source = "image_override"
                    trace.emit("input_images_received", "input", "success", "已读取图片", metadata={"image_count": len(images)})
            else:
                if trace:
                    trace.emit("model_step_started", "routing", "running", "正在理解请求…", step_id=0)
                with budget_stage_scope("understanding"):
                    decision = await self.router.route(user_message, recent_context=self._recent_routing_context(user_message))
                if trace:
                    trace.route_source = trace.route_source or "cognitive_router"
                    if not getattr(self.router, "last_provider_failed", False):
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
        if trace:
            trace.route = decision.route.value
            if trace.runtime_lane is None:
                trace.runtime_lane = ("deep" if decision.route in {CognitiveRoute.PLAN, CognitiveRoute.WORKFLOW} else "standard")
        if decision_service is not None and not images and decision.route is not CognitiveRoute.FAST_CHAT:
            planner_requested = (decision.route == CognitiveRoute.PLAN and
                                 any(marker in user_message for marker in ("还是", "或者", "选", "方向")))
            if trace:
                trace.emit("decision_started", "decision", "running", "正在检查是否需要决策…")
            result = await decision_service.evaluate(user_message, planner_requested=planner_requested)
            if trace:
                trace.emit("decision_finished", "decision", "success", "决策检查已完成",
                           metadata={"used": result is not None})
                trace.decision_used = result is not None
            if result is not None:
                reply = await self.agent.run_decision_reply(
                    user_message, result,
                    mode=decision_service.last_context.decision_mode if decision_service.last_context else "normal",
                )
                content = reply.content
                return CognitiveResponse(content=content, route=CognitiveRoute.DIRECT)
        workflow_run_id = None
        if decision.route == CognitiveRoute.FAST_CHAT:
            content = result.content
            goal_id = None
        elif decision.route == CognitiveRoute.WORKFLOW and self.agent.workflow is not None and decision.workflow_id:
            self.agent.conversation.add_user(user_message.strip())
            if trace:
                trace.emit("workflow_started", "workflow", "running", "正在执行流程…")
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
            finally:
                if trace:
                    trace.emit("workflow_finished", "workflow", "success", "流程阶段已结束")
            content = result.content
            goal_id = None
            ingress = getattr(self.agent, "cognitive_ingress", None)
            if ingress:
                from zhaoxi.cognitive_stream.models import CognitiveEventType
                ingress.record(CognitiveEventType.WORKFLOW_EVENT,
                    f"Workflow {decision.workflow_id}: {content[:300]}", source="workflow",
                    channel="desktop", session_id="local",
                    parent_refs=([current_turn().trigger_event.event_id]
                                 if current_turn() else []))
        elif decision.route == CognitiveRoute.PLAN and self.agent.planner is not None:
            if trace:
                trace.emit("planner_started", "planner", "running", "正在安排任务…")
            try:
                result = await self.agent.run_planned(user_message)
            finally:
                if trace:
                    trace.emit("planner_finished", "planner", "success", "规划阶段已结束")
            ingress = getattr(self.agent, "cognitive_ingress", None)
            if ingress:
                from zhaoxi.cognitive_stream.models import CognitiveEventType
                ingress.record(CognitiveEventType.PLANNER_EVENT,
                    f"Planner Goal {result.goal_id or 'unknown'}: {result.content[:300]}",
                    source="planner", channel="desktop", session_id="local",
                    parent_refs=([current_turn().trigger_event.event_id]
                                 if current_turn() else []))
            content = result.content
            goal_id = result.goal_id
        elif decision.route == CognitiveRoute.DIRECT:
            result = await self.agent.run_direct(
                user_message)
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
        if self.auto_memory is not None and getattr(self.agent, "experience_stream", None) is None:
            if trace:
                trace.emit("memory_maintenance_started", "memory", "running", "正在整理相关记忆…")
            try:
                with budget_stage_scope("finalization"):
                    turn = current_turn()
                    event = turn.trigger_event if turn else None
                    memory_decision = (await self.auto_memory.process_event(event, content)
                                       if event is not None else
                                       await self.auto_memory.process(user_message, content))
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

    @staticmethod
    def _route_fast_exclusion(reason: str, decision_available: bool) -> RouteDecision | None:
        if reason == "multi_step_request":
            return RouteDecision(route=CognitiveRoute.PLAN, reason=reason)
        if reason == "explicit_decision" and decision_available:
            return RouteDecision(route=CognitiveRoute.DIRECT, reason=reason)
        if reason in {
            "explicit_action", "explicit_recall", "external_or_realtime_query",
            "calculation_request", "private_or_structured_fact", "personal_fact_recall",
        }:
            return RouteDecision(
                route=CognitiveRoute.TOOL, reason=reason, requires_tool_call=True
            )
        return None
    def _recent_routing_context(self, query: str = "", limit: int = 6, max_chars: int = 2400) -> str:
        """Provide bounded dialogue context to the router without Tool observations or metadata."""
        stream = getattr(self.agent, "experience_stream", None)
        if stream is None:
            return ""
        from zhaoxi.cognitive_stream.timeline import cognitive_timeline
        messages = cognitive_timeline(
            stream, query=query, attention=getattr(self.agent, "attention_retriever", None),
            limit=limit, max_chars=max_chars,
        )
        return "\n".join(
            f"{message.role.value}: {message.content[:600]}"
            for message in messages if message.content
        )[-max_chars:]
