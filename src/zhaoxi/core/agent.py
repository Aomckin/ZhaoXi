"""The minimal extensible Zhaoxi agent loop."""

import asyncio
import copy
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.core.message import Role, strip_echoed_timeline_header
from zhaoxi.core.reply import commit_reply
from zhaoxi.errors import AgentLoopError, ProviderError
from zhaoxi.models.base import ModelProvider
from zhaoxi.models.types import ToolCall
from zhaoxi.observability import current_trace
from zhaoxi.memory.models import MemorySearchResult
from zhaoxi.permission.executor import ToolExecutor
from zhaoxi.permission.models import InvocationOrigin, PendingConfirmation
from zhaoxi.reliability import current_correlation
from zhaoxi.reliability.retry import BudgetExtensionRequest, budget_stage_scope, current_budget
from zhaoxi.tools.base import ToolResult
from zhaoxi.tools.registry import ToolRegistry
from zhaoxi.tools.discovery import RequestToolGroupTool, InspectToolCatalogTool, ToolDiscoveryState
from zhaoxi.tools.router import ToolContext, safe_resolve_tool_context
from zhaoxi.tools.manifest import is_action_request, resolve_capability

if TYPE_CHECKING:
    from zhaoxi.cognitive.coordinator import CognitiveCoordinator, CognitiveResponse
    from zhaoxi.planner.runtime import PlannerResponse, PlannerRuntime
    from zhaoxi.workflow.runtime import WorkflowRuntime

logger = logging.getLogger("AGENT")
tool_logger = logging.getLogger("TOOL")
model_logger = logging.getLogger("MODEL")

TOOL_QUERY_NOT_COMPLETED_NOTICE = "（提醒：这次没有实际调用工具，回复未经工具核验。）"
PROVIDER_DEGRADED_NOTICE = "（提醒：模型服务暂时不可用，这段回复可能不完整；已完成的工具操作已保留。）"
TOOL_ARGUMENTS_DEGRADED_NOTICE = "（提醒：模型生成的后续工具参数格式有误；上面的工具结果已保留。）"
STEP_LIMIT_NOTICE = "（提醒：工具步骤已达到本轮上限，回复可能不完整；已完成的操作已保留。）"


def log_internal_failure(message: str, *args, exc: Exception) -> None:
    """Keep tracebacks out of the normal CLI while retaining them in DEBUG."""
    if logger.isEnabledFor(logging.DEBUG):
        logger.exception(message, *args)
    else:
        logger.warning(message + " type=%s", *args, type(exc).__name__)


@dataclass(slots=True)
class AgentResponse:
    """Final user-facing response plus trace metadata."""

    content: str
    request_id: str
    steps: int
    permission_confirmation: PendingConfirmation | None = None
    used_tool_path: bool = False

    def __post_init__(self) -> None:
        self.content = strip_echoed_timeline_header(self.content)


@dataclass(slots=True)
class PendingAgentInvocation:
    request_id: str
    name: str
    arguments: dict[str, object]
    invocation_id: str
    tool_call_id: str
    user_intent: str
    remaining_calls: list[ToolCall]
    batch_call_count: int = 1
    discovery: ToolDiscoveryState | None = None
    images: tuple[str, ...] = ()


class ZhaoxiAgent:
    """Run model/tool iterations without knowing any concrete provider or tool."""

    def __init__(
        self,
        *,
        provider: ModelProvider,
        registry: ToolRegistry,
        context_builder: ContextBuilder,
        conversation: Conversation | None = None,
        max_steps: int = 8,
        timeout_seconds: float = 60,
        planner: "PlannerRuntime | None" = None,
        tool_executor: ToolExecutor | None = None,
        workflow: "WorkflowRuntime | None" = None,
        proactive=None,
        proactive_scheduler=None,
        proactive_state=None,
        tool_router_mode: str = "dynamic",
    ) -> None:
        self.provider = provider
        self.registry = registry
        for control_tool in (RequestToolGroupTool(), InspectToolCatalogTool()):
            if not any(tool.name == control_tool.name for tool in registry.list()):
                registry.register(control_tool)
        self.context_builder = context_builder
        self.emoji_service = getattr(context_builder, "emoji_service", None)
        self.conversation = conversation or Conversation()
        self.max_steps = max_steps
        self.timeout_seconds = timeout_seconds
        self.planner = planner
        self.tool_executor = tool_executor or ToolExecutor(registry)
        self.workflow = workflow
        self.proactive = proactive
        self.proactive_scheduler = proactive_scheduler
        self.proactive_state = proactive_state
        self.tool_router_mode = tool_router_mode
        self._pending_permissions: dict[str, PendingAgentInvocation] = {}
        self.cognitive: "CognitiveCoordinator | None" = None
        self.last_emoji_trace: dict[str, object] = {}

    def _commit_model_reply(self, raw_reply: str) -> str:
        """Parse, resolve and persist one final model reply exactly once."""
        sequence, message_ids = commit_reply(
            self.conversation, raw_reply, getattr(self, "emoji_service", None)
        )
        emoji_segments = [
            item for item in sequence.segments if item.type == "emoji"
        ]
        correlation = current_correlation()
        self.last_emoji_trace = {
            "trace_id": correlation.trace_id if correlation else None,
            "raw_reply": sequence.raw_reply,
            "parsed_segments": [item.model_dump(mode="json") for item in sequence.segments],
            "requested_tags": [item.requested_tags for item in emoji_segments],
            "resolved_emoji_ids": [item.emoji_id for item in emoji_segments],
            "recent_emoji_history": list(getattr(
                getattr(self, "emoji_service", None), "recent_ids", []
            )),
            "message_ids": message_ids,
            "persisted": False,
            "gateway_emitted": False,
            "frontend_received": False,
            "frontend_rendered": False,
        }
        return sequence.visible_text

    async def run_planned(self, goal: str) -> "PlannerResponse":
        """Run an explicit multi-step task through the optional planner."""
        if self.planner is None:
            raise AgentLoopError("Planner 未启用。")
        return await self.planner.run(goal)

    async def run_natural(self, user_message: str, *, images: list[str] | None = None) -> "CognitiveResponse | AgentResponse":
        """Use cognitive integration when configured, otherwise preserve v0.3 behavior."""
        pending_response = await self._handle_pending_permission_input(user_message)
        if pending_response is not None:
            return pending_response
        if self.cognitive is None:
            return await self.run(user_message, **({"images": images} if images else {}))
        return await self.cognitive.run(user_message, **({"images": images} if images else {}))

    async def _handle_pending_permission_input(
        self, user_message: str
    ) -> "AgentResponse | PlannerResponse | None":
        """Consume permission replies before routing or invoking any model."""
        agent_ids = list(self._pending_permissions)
        planner_ids = list(self.planner._pending_permissions) if self.planner else []
        workflow_runs = await self.workflow.history() if self.workflow else []
        workflow_ids = [
            item.id for item in workflow_runs if item.status.value == "waiting_for_permission"
        ]
        pending_ids = [
            *(("agent", item) for item in agent_ids),
            *(("planner", item) for item in planner_ids),
            *(("workflow", item) for item in workflow_ids),
        ]
        if not pending_ids:
            return None
        if len(pending_ids) != 1:
            return AgentResponse(
                content="当前有多个待确认操作，请使用 /permissions 查看并通过 /approve <id> 或 /deny <id> 处理。",
                request_id=uuid4().hex,
                steps=0,
            )
        owner, confirmation_id = pending_ids[0]
        if owner == "agent":
            pending_invocation = self._pending_permissions[confirmation_id]
            selection = self._permission_selection(
                user_message, pending_invocation.batch_call_count
            )
            if selection is not None:
                return await self.resolve_permission_batch(confirmation_id, selection)
        decision = self._permission_reply(user_message)
        if decision == "approve":
            if owner == "workflow":
                self.conversation.add_user(user_message.strip())
                run = await self.workflow.approve(confirmation_id)
                return await self.finalize_workflow(run)
            if owner == "planner":
                return await self.planner.approve_permission(confirmation_id)
            return await self.approve_permission(confirmation_id)
        if decision == "deny":
            if owner == "workflow":
                self.conversation.add_user(user_message.strip())
                run = await self.workflow.deny(confirmation_id)
                return await self.finalize_workflow(run)
            if owner == "planner":
                return await self.planner.deny_permission(confirmation_id)
            return await self.deny_permission(confirmation_id)
        if owner == "workflow":
            run = await self.workflow.get(confirmation_id)
            step_run = run.step_run(run.current_step_id)
            pending = self.tool_executor.gateway.store.pending[step_run.confirmation_id]
        else:
            pending = self.tool_executor.gateway.store.pending[confirmation_id]
        return AgentResponse(
            content=(
                f"有一项操作正在等待确认：{pending.request.action_summary}。"
                "请回复“允许/确认/执行”或“拒绝/不要/取消”。"
            ),
            request_id=pending.request.request_id,
            steps=0,
            permission_confirmation=pending,
        )

    def _workflow_response(self, run) -> AgentResponse:
        if run.status.value == "waiting_for_permission":
            content = "这个操作需要你的确认。请回复“确认”继续，或回复“取消”。"
        elif run.status.value == "waiting_for_input":
            content = run.pending_question or "还需要补充一些信息才能继续。"
        elif run.status.value == "completed":
            content = self._workflow_fallback(run)
        else:
            content = self._workflow_fallback(run)
        confirmation = None
        if run.status.value == "waiting_for_permission" and run.current_step_id:
            step_run = run.step_run(run.current_step_id)
            if step_run.confirmation_id:
                confirmation = self.tool_executor.gateway.store.pending.get(step_run.confirmation_id)
        return AgentResponse(content=content, request_id=run.id, steps=0, permission_confirmation=confirmation)

    async def finalize_workflow(self, run) -> AgentResponse:
        """Turn an internal Workflow observation into a normal assistant reply."""
        if run.status.value in {"waiting_for_permission", "waiting_for_input"}:
            response = self._workflow_response(run)
            self.conversation.add_assistant(response.content)
            return response
        observation = {
            "workflow_id": run.workflow_id,
            "status": run.status.value,
            "result": run.result,
            "error": run.error,
        }
        messages = self.context_builder.build(self.conversation)
        messages[0].content = (
            (messages[0].content or "")
            + "\n\n内部 Workflow 执行结果（只作为事实，不得原样输出 JSON、字段名或内部对象）：\n"
            + json.dumps(observation, ensure_ascii=False, default=str)
            + "\n请结合用户原意，用自然、简洁的中文给出最终回复；失败时如实说明，不猜测成功。"
        )
        content = ""
        try:
            with budget_stage_scope("finalization"):
                model_response = await asyncio.wait_for(
                    self.provider.generate(messages, None), timeout=self.timeout_seconds
                )
            content = strip_echoed_timeline_header((model_response.content or "").strip())
        except Exception as exc:
            logger.warning("workflow final response fallback run=%s error=%s", run.id, type(exc).__name__)
        if not content:
            content = self._workflow_fallback(run)
        content = self._commit_model_reply(content)
        return AgentResponse(content=content, request_id=run.id, steps=0)

    @staticmethod
    def _workflow_response_error(content: str, trace_id: str) -> AgentResponse:
        return AgentResponse(content=content, request_id=trace_id, steps=0)

    @staticmethod
    def _workflow_fallback(run) -> str:
        message = run.result.get("message") if isinstance(run.result, dict) else None
        if isinstance(message, str) and message.strip():
            return message.strip()
        if run.status.value == "cancelled":
            return "已取消，这次没有继续执行。"
        if run.status.value == "failed":
            return "这次流程没有顺利完成，相关状态没有被当作成功处理。"
        return "流程已经处理完成。"

    @staticmethod
    def _permission_reply(value: str) -> str | None:
        normalized = re.sub(r"[\s，,。.!！?？、]", "", value.strip().lower())
        approve_values = {"允许", "确认", "执行", "允许执行", "确认执行", "可以", "同意"}
        deny_values = {"拒绝", "不要", "取消", "不允许", "不要执行", "拒绝执行"}
        if normalized in approve_values:
            return "approve"
        if normalized in deny_values:
            return "deny"
        return None

    @classmethod
    def _permission_selection(cls, value: str, batch_size: int) -> set[int] | None:
        """Parse a conservative 1-based partial selection for one pending batch."""
        if batch_size <= 1:
            return None
        compact = value.strip().lower()
        if not any(marker in compact for marker in ("删", "执行", "允许", "保留", "拒绝", "取消")):
            return None
        approve_match = re.search(
            r"(?:只?(?:删(?:除)?|执行|允许))(.+?)(?=保留|不删|拒绝|取消|$)", compact
        )
        keep_match = re.search(r"(?:保留|不删|拒绝|取消)(.+)$", compact)
        approved = cls._parse_positions(approve_match.group(1), batch_size) if approve_match else None
        kept = cls._parse_positions(keep_match.group(1), batch_size) if keep_match else None
        if approved is None and kept is None:
            return None
        all_positions = set(range(1, batch_size + 1))
        if approved is None:
            approved = all_positions - kept
        if kept is not None and approved & kept:
            return None
        return approved if approved <= all_positions else None

    @staticmethod
    def _parse_positions(segment: str, batch_size: int) -> set[int] | None:
        value = segment.strip(" ：:，,。.!！、")
        if not value:
            return None
        tokens = re.findall(r"\d+", value)
        if not tokens:
            return None
        has_separator = bool(re.search(r"[、,，\s和与]", value))
        if len(tokens) == 1 and not has_separator:
            token = tokens[0]
            number = int(token)
            if number <= batch_size:
                positions = {number}
            elif batch_size <= 9 and all(1 <= int(char) <= batch_size for char in token):
                positions = {int(char) for char in token}
            else:
                return None
        else:
            positions = {int(token) for token in tokens}
        if not positions or any(position < 1 or position > batch_size for position in positions):
            return None
        return positions

    async def run(
        self,
        user_message: str,
        *,
        require_tool_call: bool = False,
        required_tool: str | None = None,
        images: list[str] | None = None,
    ) -> AgentResponse:
        """Accept one user turn and return a final natural-language response."""
        if not user_message.strip():
            raise ValueError("消息不能为空。")
        correlation = current_correlation()
        request_id = correlation.request_id if correlation and correlation.request_id else uuid4().hex
        clean_message = user_message.strip()
        self.conversation.add_user(clean_message, images=images)
        trace = current_trace()
        if images and trace and not any(event.event_type == "input_images_received" for event in trace.events):
            trace.emit("input_images_received", "input", "success", "已读取图片",
                       metadata={"image_count": len(images)})
        logger.info("request=%s received user input", request_id)
        memories = []
        if self.context_builder.memory_retriever:
            trace = current_trace()
            if trace:
                trace.emit("memory_search_started", "memory_search", "running", "正在检索相关记忆…")
            try:
                memories = await self.context_builder.memory_retriever.retrieve(clean_message)
                if trace:
                    trace.emit("memory_search_finished", "memory_search", "success", "已检索相关记忆", metadata={"hit_count": len(memories)})
                logger.info("request=%s memory_hits=%d", request_id, len(memories))
            except Exception as exc:
                if trace:
                    trace.emit("memory_search_failed", "memory_search", "warning", "记忆检索未完成，继续处理", error_code="memory_search_error", metadata={"error_type": type(exc).__name__})
                log_internal_failure(
                    "request=%s memory retrieval failed; continuing without memory",
                    request_id,
                    exc=exc,
                )
        try:
            return await asyncio.wait_for(
                self._run_loop(
                    request_id,
                    memories,
                    clean_message,
                    require_tool_call=require_tool_call,
                    required_tool=required_tool,
                    turn_images=tuple(images or ()),
                ),
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            logger.error("request=%s timed out", request_id)
            raise AgentLoopError(f"请求超过 {self.timeout_seconds:g} 秒，已停止。") from exc

    @staticmethod
    def _promises_lookup(content: str) -> bool:
        """Catch a current-turn tool commitment, not a casual guess or capability claim."""
        for clause in re.split(r"[。！？!?\n]", content):
            if re.search(r"(?:不|没|无法|不能|不用|不必|别)(?:会|能|再|去|用|要)?(?:查|查询|检查|读取|翻|调用)", clause):
                continue
            if re.search(r"我(?:现在|这就|马上|直接|先|来|去|会|要|就|再|帮你|替你){1,5}(?:查|查询|检查|读取|检索|调用|翻|看看)", clause):
                return True
        return False

    async def run_direct(self, user_message: str) -> AgentResponse:
        """Answer a direct turn while preserving the always-on memory tools."""
        if not user_message.strip():
            raise ValueError("消息不能为空。")
        correlation = current_correlation()
        request_id = correlation.request_id if correlation and correlation.request_id else uuid4().hex
        clean_message = user_message.strip()
        self.conversation.add_user(clean_message)
        memories = []
        if self.context_builder.memory_retriever:
            trace = current_trace()
            if trace:
                trace.emit("memory_search_started", "memory_search", "running", "正在检索相关记忆…")
            try:
                memories = await self.context_builder.memory_retriever.retrieve(clean_message)
                if trace:
                    trace.emit("memory_search_finished", "memory_search", "success", "已检索相关记忆", metadata={"hit_count": len(memories)})
            except Exception as exc:
                if trace:
                    trace.emit("memory_search_failed", "memory_search", "warning", "记忆检索未完成，继续处理", error_code="memory_search_error", metadata={"error_type": type(exc).__name__})
                log_internal_failure(
                    "request=%s memory retrieval failed; continuing without memory",
                    request_id,
                    exc=exc,
                )
        try:
            return await asyncio.wait_for(
                self._run_loop(request_id, memories, clean_message),
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            raise AgentLoopError(f"请求超过 {self.timeout_seconds:g} 秒，已停止。") from exc

    async def resume_current_turn(self, user_message: str) -> AgentResponse:
        """Continue an interrupted model turn without replaying completed tools."""
        correlation = current_correlation()
        request_id = correlation.request_id if correlation and correlation.request_id else uuid4().hex
        memories = []
        if self.context_builder.memory_retriever:
            try:
                memories = await self.context_builder.memory_retriever.retrieve(user_message)
            except Exception as exc:
                log_internal_failure(
                    "request=%s memory retrieval failed while resuming",
                    request_id,
                    exc=exc,
                )
        try:
            return await asyncio.wait_for(
                self._run_loop(
                    request_id,
                    memories,
                    user_message,
                    discovery=getattr(self, "_tool_discovery_state", None),
                    turn_images=next((tuple(item.images) for item in reversed(self.conversation.messages)
                                      if item.role is Role.USER), ()),
                ),
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            raise AgentLoopError(f"请求超过 {self.timeout_seconds:g} 秒，已停止。") from exc

    def _recent_tool_context(self, limit: int = 6) -> list[str]:
        return [
            message.content[:600]
            for message in self.conversation.recent(limit)
            if message.role.value in {"user", "assistant"} and message.content
        ]

    def _recoverable_turn_content(self, notice: str) -> str | None:
        """Recover a bounded status reply without exposing raw tool payloads."""
        trace = current_trace()
        if trace is not None and trace.actions:
            groups: dict[str, list[str]] = {"completed": [], "failed": [], "unknown": []}
            for action in trace.actions:
                if action.status in groups:
                    groups[action.status].append(action.tool_name)
            lines = []
            for title, key in (("已完成", "completed"), ("仍失败", "failed"), ("结果未知", "unknown")):
                counts: dict[str, int] = {}
                for name in groups[key]:
                    counts[name] = counts.get(name, 0) + 1
                items = "、".join(f"{name} ×{count}" if count > 1 else name for name, count in counts.items())
                lines.append(f"{title}：{items or '无'}")
            return "\n".join(lines) + f"\n\n{notice}"
        draft = ""
        tool_successes = 0
        tool_failures = 0
        for message in reversed(self.conversation.messages):
            if message.role.value == "user":
                break
            if message.role.value == "assistant" and message.content and not draft:
                draft = message.content.strip()
            elif message.role.value == "tool" and message.content:
                try:
                    payload = json.loads(message.content)
                except (TypeError, ValueError):
                    payload = None
                if isinstance(payload, dict):
                    if payload.get("success") is True:
                        tool_successes += 1
                    else:
                        tool_failures += 1
        if tool_successes and tool_failures:
            body = "部分工具操作已经完成，部分操作未能完成；模型没能整理成自然语言回复。"
        elif tool_failures:
            body = "工具操作未能完成，模型也没能生成对应说明。"
        elif tool_successes:
            body = "工具操作已经完成，但模型没能整理成自然语言回复。"
        else:
            body = draft
        if not body:
            return None
        return f"{body.rstrip()}\n\n{notice}"

    def _return_degraded(self, request_id: str, step: int, notice: str) -> AgentResponse | None:
        trace = current_trace()
        if trace:
            trace.emit("recovery_started", "recovery", "running", "正在整理已执行操作…", step_id=step)
        content = self._recoverable_turn_content(notice)
        if content is None:
            if trace:
                trace.emit("recovery_failed", "recovery", "failed", "无法确认本次操作结果", step_id=step,
                           error_code="response_generation_error")
            return None
        self.conversation.add_assistant(content)
        if trace:
            trace.emit("recovery_finished", "recovery", "success", "已整理操作结果", step_id=step,
                       metadata={"task_status": trace.task_status})
        return AgentResponse(
            content=content,
            request_id=request_id,
            steps=step,
            used_tool_path=True,
        )

    def _tool_context(self, user_intent: str) -> ToolContext:
        context = safe_resolve_tool_context(
            user_intent, self._recent_tool_context(), self.registry, mode=self.tool_router_mode
        )
        if context.fallback:
            logger.error("tool router failed; using persistent fallback")
        return context

    def _observable_tool_name(self, name: str) -> str:
        return name if any(tool.name == name for tool in self.registry.list()) else "unknown_tool"

    @staticmethod
    def _budget_mode(tool_called: bool, trace, step: int) -> tuple[str, bool]:
        """Spend normal budget on actions; switch to a tool-free closing call when needed."""
        budget = current_budget()
        stage = "tool_execution" if tool_called else "planning"
        if budget is None or budget.policy is None:
            return stage, False
        threshold = (budget.max_total_tokens - budget.finalization_reserve) * budget.policy.warning_ratio
        if budget.total_tokens < threshold:
            return stage, False
        actions = [item for item in (trace.actions if trace else []) if item.status != "superseded"]
        completed = [item for item in actions if item.status == "completed"]
        failures = [item for item in actions if item.status == "failed"]
        last = actions[-1] if actions else None
        repeated = (sum(item.tool_name == last.tool_name and item.failure_kind == last.failure_kind
                        for item in failures[-3:]) if last and last.status == "failed" else 0)
        evidence = {"completed_actions": len(completed),
                    "last_success_step": completed[-1].step_id if completed else None,
                    "new_result": bool(last and last.failure_kind == "validation" and repeated < 2),
                    "repeated_error_count": repeated,
                    "stalled_rounds": step - (completed[-1].step_id or step) if completed else 0}
        if completed and budget.extension_count == 0 and budget.total_tokens >= budget.max_total_tokens and budget.policy.extension_1_limit > 0:
            budget.request_extension(BudgetExtensionRequest(
                reason="已完成业务操作，需为最终回复补足预算", remaining_actions=0,
                estimated_extra_tokens=budget.policy.extension_1_limit,
                stage="finalization", progress_evidence=evidence))
            return "finalization", True
        if budget.extension_count == 0 and budget.policy.extension_1_limit > 0 and (len(completed) >= 2 or evidence["new_result"]):
            budget.request_extension(BudgetExtensionRequest(
                reason="仍有明确操作或一次可修正的工具调用", remaining_actions=1,
                estimated_extra_tokens=budget.policy.extension_1_limit,
                stage="tool_execution", progress_evidence=evidence))
        elif budget.extension_count == 1 and completed and budget.policy.extension_2_limit > 0:
            budget.request_extension(BudgetExtensionRequest(
                reason="已完成业务操作，需要整理最终状态", remaining_actions=0,
                estimated_extra_tokens=budget.policy.extension_2_limit,
                stage="finalization", progress_evidence=evidence))
            return "finalization", True
        if completed and budget.total_tokens >= budget.max_total_tokens - budget.finalization_reserve:
            return "finalization", True
        return stage, False

    async def _run_loop(
        self,
        request_id: str,
        memories: list[MemorySearchResult] | None = None,
        user_intent: str = "",
        require_tool_call: bool = False,
        required_tool: str | None = None,
        lookup_commitment: str = "",
        discovery: ToolDiscoveryState | None = None,
        turn_images: tuple[str, ...] = (),
    ) -> AgentResponse:
        if discovery is None:
            routing_intent = f"{user_intent}\n{lookup_commitment}" if lookup_commitment else user_intent
            discovery = ToolDiscoveryState(self._tool_context(routing_intent))
        self._tool_discovery_state = discovery
        capability_retry = False
        resolution_message = ""
        tool_called = discovery.business_tool_called
        corrective_retry = bool(lookup_commitment)
        trace = current_trace()
        response_started = False
        for step in range(1, self.max_steps + 1):
            model_logger.info("request=%s step=%d calling model", request_id, step)
            if trace:
                trace.current_step = step
                if tool_called and not response_started:
                    trace.emit("response_generation_started", "response_generation", "running", "正在整理回复…", step_id=step)
                    response_started = True
                trace.emit("model_step_started", "model", "running", "正在思考下一步…", step_id=step)
            try:
                budget_stage, final_only = self._budget_mode(tool_called, trace, step)
                schemas = [] if final_only else discovery.schemas(self.registry)
                self.registry.exposed_names = {item["function"]["name"] for item in schemas}
                absorbed = set()
                if trace and trace.actions:
                    for action in trace.actions[:-1]:
                        if action.status != "completed":
                            continue
                        try:
                            tool = self.registry.get(action.tool_name)
                        except KeyError:
                            continue
                        if tool.mutates_state:
                            absorbed.add(action.tool_call_id)
                context_options = {}
                if absorbed:
                    context_options["absorbed_tool_call_ids"] = absorbed
                if final_only:
                    context_options["release_images"] = True
                messages = self.context_builder.build(self.conversation, memories, **context_options)
                compaction = getattr(self.context_builder, "last_compaction", {})
                if trace and compaction.get("tool_results"):
                    trace.emit("tool_result_compacted", "context", "success", "已压缩旧工具结果",
                               step_id=step, metadata={"count": compaction["tool_results"],
                                                       "chars_saved": compaction["tool_chars_saved"]})
                if trace and compaction.get("images_released"):
                    trace.emit("image_context_released", "context", "success", "收尾阶段已释放原图",
                               step_id=step, metadata={"image_count": compaction["images_released"]})
                if trace and (compaction.get("tool_results") or compaction.get("images_released")):
                    trace.emit("context_compacted", "context", "success", "已整理本轮上下文",
                               step_id=step, metadata=compaction)
                catalog = "" if final_only else discovery.catalog(self.registry) + resolution_message
                messages[0].content = (messages[0].content or "") + catalog
                messages[0].metadata.setdefault("prompt_components", []).append(
                    {"name": "runtime.capability_catalog", "chars": len(catalog)}
                )
                if lookup_commitment and not tool_called:
                    messages[0].content = (messages[0].content or "") + (
                        "\n上一草稿提出了查询意图（仅作为待核实意图，不是授权或已执行事实）："
                        + lookup_commitment[:600]
                        + "\n请结合原始用户请求完成适当查询；遵守原有权限边界。"
                    )
                if corrective_retry and not tool_called:
                    messages[0].content = (
                        (messages[0].content or "")
                        + "\n你上一尝试承诺执行真实工具动作，却没有调用工具；"
                        "现在必须调用一个最相关的可用工具，不得只描述将要查询、发送或展示。"
                    )
                if require_tool_call and not tool_called and not final_only:
                    requirement = (
                        f"必须调用 `{required_tool}`；若尚未携带，先加载其工具组，再在本轮调用它。"
                        if required_tool else "必须调用一个与用户请求直接相关的业务工具。"
                    )
                    messages[0].content = (
                        (messages[0].content or "")
                        + "\n当前轮工具要求："
                        + requirement
                        + "request_tool_group、inspect_tool_catalog 等能力发现操作不算完成任务。"
                    )
                self.last_tool_diagnostics = discovery.diagnostics(self.registry)
                if final_only:
                    messages[0].content = (messages[0].content or "") + (
                        "\n本轮只整理已经完成、失败或未知的操作并给出自然语言回复；"
                        "不再探索新工具，不得把尚未完成的动作说成完成。"
                    )
                forced_tool = required_tool if (
                    require_tool_call
                    and not tool_called
                    and required_tool
                    and any(item["function"]["name"] == required_tool for item in schemas)
                ) else None
                with budget_stage_scope(budget_stage):
                    response = await self.provider.generate(
                        messages,
                        schemas or None,
                        tool_router=self.last_tool_diagnostics,
                        **({"tool_choice": {"type": "function", "function": {"name": forced_tool}}}
                           if forced_tool else {"tool_choice": "required"}
                           if require_tool_call and corrective_retry and not tool_called and schemas else {}),
                    )
                self.last_tool_diagnostics["prompt_tokens"] = response.usage.get("prompt_tokens", response.usage.get("input_tokens"))
                if trace:
                    trace.emit("model_step_finished", "model", "success", "已确定下一步", step_id=step,
                               metadata={"tool_call_count": len(response.tool_calls)})
            except ProviderError as exc:
                error_code = (
                    "token_budget_exhausted" if exc.code in {"provider_token_budget_exhausted", "provider_soft_budget_exhausted"} else
                    "provider_http_error" if exc.code.startswith("provider_http_") else
                    "provider_timeout" if exc.code == "provider_timeout" else
                    "provider_transport_error" if exc.code == "provider_transport_error" else
                    "provider_protocol_error" if exc.code in {"provider_response_invalid", "provider_tool_arguments_invalid"} else
                    "agent_loop_error" if exc.code == "provider_call_budget_exhausted" else "provider_protocol_error"
                )
                if trace:
                    trace.emit("model_step_failed", "model", "failed", "模型请求失败" if error_code != "token_budget_exhausted" else "本次请求 Token 预算已耗尽",
                               step_id=step, error_code=error_code,
                               metadata={"provider_error_code": exc.code})
                    trace.emit("response_generation_failed", "response_generation", "failed",
                               "最终回复生成失败" if error_code != "token_budget_exhausted" else "回复生成失败：本次请求 Token 预算耗尽",
                               step_id=step, error_code=error_code)
                    trace.response_status = "failed"
                log_internal_failure("request=%s provider error", request_id, exc=exc)
                if tool_called:
                    notice = (
                        TOOL_ARGUMENTS_DEGRADED_NOTICE
                        if exc.code == "provider_tool_arguments_invalid"
                        else "（提醒：本次任务累计 Token 已达到预算上限，最终回复未能继续生成；已完成的操作均已保留。）"
                        if error_code == "token_budget_exhausted"
                        else PROVIDER_DEGRADED_NOTICE
                    )
                    degraded = self._return_degraded(
                        request_id, step, notice
                    )
                    if degraded is not None:
                        logger.warning(
                            "request=%s provider error after tool call; returning tool-aware response code=%s",
                            request_id,
                            exc.code,
                        )
                        return degraded
                if exc.code == "provider_tool_arguments_invalid":
                    raise AgentLoopError(
                        "模型返回的工具调用参数格式有误，本次未执行该工具。", code=error_code
                    ) from exc
                if error_code == "token_budget_exhausted":
                    raise AgentLoopError("本次任务累计 Token 已达到预算上限，最终回复未能继续生成。", code=error_code) from exc
                raise AgentLoopError(
                    "模型服务当前不可访问，请稍后重试；"
                    + (
                        "已经完成的工具操作会保留，重新生成只会继续生成回复。"
                        if tool_called
                        else "这次没有执行任何新的工具操作。"
                    ), code=error_code
                ) from exc

            if not response.tool_calls:
                if (not tool_called and not capability_retry and is_action_request(user_intent)
                    and re.search(r"没有.{0,12}(?:工具|能力|钥匙)|无法完成|做不了|不能.{0,6}(?:查|找|读|执行)", response.content or "")):
                    capability_retry = True
                    resolution = resolve_capability(user_intent, self.registry.manifest())
                    discovery.resolution_checked = True
                    if resolution["groups"]:
                        for group in resolution["groups"]:
                            discovery.request({"group": group}, self.registry)
                        resolution_message = "\nCore 已检查实时钥匙柜并尝试加载匹配能力：" + json.dumps(resolution, ensure_ascii=False) + "。请使用当前可用钥匙继续原任务，不要把未携带误判为不存在。"
                        continue
                if not tool_called and self._promises_lookup(response.content or ""):
                    require_tool_call = True
                if require_tool_call and not tool_called and not corrective_retry:
                    corrective_retry = True
                    logger.warning("request=%s required tool call missing; retrying once", request_id)
                    continue
                content = strip_echoed_timeline_header(response.content or "模型没有返回可显示的内容。")
                if require_tool_call and not tool_called:
                    logger.warning(
                        "request=%s required tool call missing after retry; returning response with notice",
                        request_id,
                    )
                    content = f"{content.rstrip()}\n\n{TOOL_QUERY_NOT_COMPLETED_NOTICE}"
                if trace and not response_started:
                    trace.emit("response_generation_started", "response_generation", "running", "正在整理回复…", step_id=step)
                try:
                    content = self._commit_model_reply(content)
                except Exception as exc:
                    if trace:
                        trace.emit("response_generation_failed", "response_generation", "failed",
                                   "回复整理失败", step_id=step, error_code="response_generation_error",
                                   metadata={"error_type": type(exc).__name__})
                        trace.response_status = "failed"
                    raise AgentLoopError("回复整理失败，请重试。", code="response_generation_error") from exc
                if trace:
                    trace.emit("response_generation_succeeded", "response_generation", "success", "回复已生成", step_id=step)
                    trace.response_status = "succeeded"
                logger.info("request=%s final response step=%d", request_id, step)
                return AgentResponse(
                    content=content, request_id=request_id, steps=step,
                    used_tool_path=tool_called,
                )

            control_names = {"request_tool_group", "inspect_tool_catalog"}
            business_calls = [call for call in response.tool_calls if call.name not in control_names]
            # Discovery controls mutate only this turn's schema selection. Replaying
            # them as provider tool transcripts is both unnecessary and rejected by
            # providers that emitted the control call through a textual protocol.
            if business_calls:
                transcript_metadata = {
                    key: response.raw_metadata[key]
                    for key in ("reasoning_content", "tool_call_transport")
                    if key in response.raw_metadata
                }
                self.conversation.add_assistant(response.content, tool_calls=business_calls,
                    metadata=transcript_metadata)
            for call_index, call in enumerate(response.tool_calls):
                observable_name = self._observable_tool_name(call.name)
                tool_logger.info(
                    "request=%s tool=%s argument_keys=%s",
                    request_id,
                    observable_name,
                    sorted(str(key) for key in call.arguments if key in self.registry.get(call.name).input_model.model_fields)
                    if observable_name != "unknown_tool" else [],
                )
                if call.name in {"request_tool_group", "inspect_tool_catalog"}:
                    result = self._run_control_tool(call, discovery)
                    discovery.record_observation(call.name, result)
                    if (call.name == "inspect_tool_catalog" and result.success
                        and call.arguments.get("action", "summary") != "resolve"
                        and re.search(r"钥匙|工具|能力|tool", user_intent, re.IGNORECASE)):
                        tool_called = discovery.business_tool_called = True
                    continue
                tool_called = discovery.business_tool_called = True
                invocation_id = uuid4().hex
                attempt = trace.start_tool(observable_name, call.id, invocation_id, step) if trace else None
                execution = await self.tool_executor.execute(
                    call.name,
                    call.arguments,
                    request_id=request_id,
                    origin=InvocationOrigin.AGENT,
                    user_intent=user_intent,
                    invocation_id=invocation_id,
                    step_id=str(step),
                    image_attachments=turn_images if call.name == "lifehud" else None,
                )
                if execution.waiting_for_permission:
                    if trace:
                        trace.emit("tool_call_waiting_permission", "tool_execution", "info",
                                   "操作正在等待确认", step_id=step, tool_name=observable_name,
                                   tool_call_id=call.id, invocation_id=invocation_id)
                    confirmation = execution.confirmation
                    remaining_calls = copy.deepcopy(response.tool_calls[call_index + 1:])
                    batch_call_count = self._mergeable_batch_count(call, remaining_calls)
                    self._describe_batch_confirmation(
                        confirmation,
                        [call, *remaining_calls[: batch_call_count - 1]],
                    )
                    self._pending_permissions[confirmation.confirmation_id] = PendingAgentInvocation(
                        request_id=request_id,
                        name=call.name,
                        arguments=copy.deepcopy(call.arguments),
                        invocation_id=execution.request.invocation_id,
                        tool_call_id=call.id,
                        user_intent=user_intent,
                        remaining_calls=remaining_calls,
                        batch_call_count=batch_call_count,
                        discovery=discovery,
                        images=turn_images,
                    )
                    return AgentResponse(
                        content=confirmation.question,
                        request_id=request_id,
                        steps=step,
                        permission_confirmation=confirmation,
                    )
                result = execution.result
                self._record_tool_result(call, result)
                if trace and attempt:
                    self._finish_traced_tool(trace, attempt, execution)
                tool_logger.info("request=%s tool=%s success=%s", request_id, observable_name, result.success)

        logger.error("request=%s reached max steps=%d", request_id, self.max_steps)
        if trace:
            trace.emit("response_generation_failed", "response_generation", "failed",
                       "回复未能在步骤上限内完成", step_id=self.max_steps,
                       error_code="agent_loop_error")
            trace.response_status = "failed"
        degraded = self._return_degraded(request_id, self.max_steps, STEP_LIMIT_NOTICE)
        if degraded is not None:
            return degraded
        raise AgentLoopError(f"已达到最大执行步数（{self.max_steps}），为避免无限循环已停止。")

    def _run_control_tool(self, call: ToolCall, discovery: ToolDiscoveryState) -> ToolResult:
        if not self.registry.usable(call.name):
            return ToolResult(success=False, content="这把钥匙已停用或不可用。", error="tool_unavailable")
        handler = discovery.request if call.name == "request_tool_group" else discovery.inspect
        return handler(call.arguments, self.registry)

    async def approve_permission(self, confirmation_id: str) -> AgentResponse:
        """Approve and resume the exact immutable Tool Call that was paused."""
        pending = self._pending_permissions[confirmation_id]
        return await self.resolve_permission_batch(
            confirmation_id, set(range(1, pending.batch_call_count + 1))
        )

    async def resolve_permission_batch(
        self, confirmation_id: str, approved_positions: set[int]
    ) -> AgentResponse:
        """Resolve every frozen member, approving only selected 1-based positions."""
        pending = self._pending_permissions[confirmation_id]
        batch_calls = [
            ToolCall(id=pending.tool_call_id, name=pending.name, arguments=pending.arguments),
            *pending.remaining_calls[: pending.batch_call_count - 1],
        ]
        valid_positions = set(range(1, len(batch_calls) + 1))
        if not approved_positions <= valid_positions:
            raise AgentLoopError("批量权限选择包含无效序号。")
        if approved_positions:
            self.tool_executor.gateway.approve(confirmation_id)
        else:
            self.tool_executor.gateway.deny(confirmation_id)

        for position, call in enumerate(batch_calls, start=1):
            trace = current_trace()
            invocation_id = pending.invocation_id if position == 1 else uuid4().hex
            attempt = trace.start_tool(self._observable_tool_name(call.name), call.id, invocation_id, None) if trace else None
            if position in approved_positions:
                execution = await self.tool_executor.execute(
                    call.name,
                    call.arguments,
                    request_id=pending.request_id,
                    origin=InvocationOrigin.AGENT,
                    user_intent=pending.user_intent,
                    invocation_id=invocation_id,
                    approved_batch_confirmation_id=(
                        confirmation_id if position > 1 else None
                    ),
                    image_attachments=pending.images if call.name == "lifehud" else None,
                )
                if execution.result is None:
                    raise AgentLoopError("授权未能匹配批量工具调用。")
                result = execution.result
            else:
                result = ToolResult(
                    success=False,
                    content="用户选择保留该项，工具没有执行。",
                    error="permission_denied",
                )
            self._record_tool_result(call, result)
            if trace and attempt:
                if position in approved_positions:
                    self._finish_traced_tool(trace, attempt, execution)
                else:
                    trace.finish_tool(attempt, success=False, failure_kind="permission")
        del self._pending_permissions[confirmation_id]
        tail_pending = PendingAgentInvocation(
            request_id=pending.request_id,
            name=pending.name,
            arguments=pending.arguments,
            invocation_id=pending.invocation_id,
            tool_call_id=pending.tool_call_id,
            user_intent=pending.user_intent,
            remaining_calls=copy.deepcopy(
                pending.remaining_calls[pending.batch_call_count - 1:]
            ),
            batch_call_count=1,
            discovery=pending.discovery,
            images=pending.images,
        )
        continued = await self._execute_remaining_calls(tail_pending)
        if continued is not None:
            return continued
        return await self._run_loop(pending.request_id, user_intent=pending.user_intent,
                                    discovery=pending.discovery, turn_images=pending.images)

    def _record_tool_result(self, call: ToolCall, result: ToolResult) -> None:
        provider_result = result
        if not result.success:
            provider_result = result.model_copy(deep=True)
            provider_result.metadata["assistant_guidance"] = (
                "请根据这次失败结果向用户说明未完成及原因；"
                "除非你已获得修正后的有效参数，否则不要重复调用同一工具。"
            )
        self.conversation.add_tool(
            json.dumps(provider_result.model_dump(mode="json"), ensure_ascii=False),
            tool_call_id=call.id,
            name=call.name,
        )

    @staticmethod
    def _finish_traced_tool(trace, attempt, execution) -> None:
        result = execution.result
        if result is None:
            return
        data = result.data if isinstance(result.data, dict) else {}
        item = data.get("item") if isinstance(data.get("item"), dict) else {}
        raw_id = item.get("id") or data.get("id") or data.get("record_id")
        record_id = hashlib.sha256(str(raw_id).encode()).hexdigest()[:12] if raw_id else None
        result_code = result.metadata.get("result_code")
        if not isinstance(result_code, str):
            result_code = "created" if data.get("created") is True else "updated" if data.get("created") is False else "success" if result.success else None
        elif not re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", result_code):
            result_code = "success" if result.success else "failed"
        trace.finish_tool(attempt, success=result.success,
                          failure_kind=execution.failure_kind or ("execution" if not result.success else None),
                          unknown=bool(result.metadata.get("unknown_outcome")),
                          result_code=result_code, record_id=record_id,
                          metadata=execution.safe_metadata)

    async def _execute_remaining_calls(
        self,
        pending: PendingAgentInvocation,
    ) -> AgentResponse | None:
        """Finish the untouched tail of a multi-call model response after approval."""
        for index, call in enumerate(pending.remaining_calls):
            if call.name in {"request_tool_group", "inspect_tool_catalog"} and pending.discovery is not None:
                result = self._run_control_tool(call, pending.discovery)
                pending.discovery.record_observation(call.name, result)
                continue
            if pending.discovery is not None:
                pending.discovery.business_tool_called = True
            trace = current_trace()
            invocation_id = uuid4().hex
            attempt = trace.start_tool(self._observable_tool_name(call.name), call.id, invocation_id, None) if trace else None
            execution = await self.tool_executor.execute(
                call.name,
                call.arguments,
                request_id=pending.request_id,
                origin=InvocationOrigin.AGENT,
                user_intent=pending.user_intent,
                invocation_id=invocation_id,
                image_attachments=pending.images if call.name == "lifehud" else None,
            )
            if execution.waiting_for_permission:
                if trace:
                    trace.emit("tool_call_waiting_permission", "tool_execution", "info",
                               "操作正在等待确认", tool_name=self._observable_tool_name(call.name),
                               tool_call_id=call.id, invocation_id=invocation_id)
                confirmation = execution.confirmation
                remaining_calls = copy.deepcopy(pending.remaining_calls[index + 1:])
                batch_call_count = self._mergeable_batch_count(call, remaining_calls)
                self._describe_batch_confirmation(
                    confirmation,
                    [call, *remaining_calls[: batch_call_count - 1]],
                )
                self._pending_permissions[confirmation.confirmation_id] = PendingAgentInvocation(
                    request_id=pending.request_id,
                    name=call.name,
                    arguments=copy.deepcopy(call.arguments),
                    invocation_id=execution.request.invocation_id,
                    tool_call_id=call.id,
                    user_intent=pending.user_intent,
                    remaining_calls=remaining_calls,
                    batch_call_count=batch_call_count,
                    discovery=pending.discovery,
                    images=pending.images,
                )
                return AgentResponse(
                    content=confirmation.question,
                    request_id=pending.request_id,
                    steps=0,
                    permission_confirmation=confirmation,
                )
            self._record_tool_result(call, execution.result)
            if trace and attempt:
                self._finish_traced_tool(trace, attempt, execution)
        return None

    @staticmethod
    def _mergeable_batch_count(first: ToolCall, remaining: list[ToolCall]) -> int:
        """Merge only the consecutive same-Tool calls from one model response."""
        count = 1
        for call in remaining:
            if call.name != first.name:
                break
            count += 1
        return count

    def _describe_batch_confirmation(
        self, confirmation: PendingConfirmation, batch_calls: list[ToolCall]
    ) -> None:
        batch_call_count = len(batch_calls)
        if batch_call_count <= 1:
            return
        tool = self.registry.get(batch_calls[0].name)
        scopes = [tool.resource_scope(call.arguments) for call in batch_calls]
        scope_summary = "、".join(
            f"{index}.{scope}" for index, scope in enumerate(scopes[:6], start=1)
        )
        if len(scopes) > 6:
            scope_summary += f" 等 {len(scopes)} 项"
        confirmation.question = (
            f"是否允许朝汐批量执行 {batch_call_count} 项同类操作："
            f"{confirmation.request.action_summary}？范围：{scope_summary}。"
        )
        confirmation.risk_summary += f" 本次批准仅覆盖当前模型响应中冻结的 {batch_call_count} 个调用。"

    async def deny_permission(self, confirmation_id: str) -> AgentResponse:
        return await self.resolve_permission_batch(confirmation_id, set())
