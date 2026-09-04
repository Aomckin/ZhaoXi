"""The minimal extensible Zhaoxi agent loop."""

import asyncio
import copy
import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.errors import AgentLoopError, ProviderError
from zhaoxi.models.base import ModelProvider
from zhaoxi.models.types import ToolCall
from zhaoxi.memory.models import MemorySearchResult
from zhaoxi.permission.executor import ToolExecutor
from zhaoxi.permission.models import InvocationOrigin, PendingConfirmation
from zhaoxi.tools.base import ToolResult
from zhaoxi.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from zhaoxi.cognitive.coordinator import CognitiveCoordinator, CognitiveResponse
    from zhaoxi.planner.runtime import PlannerResponse, PlannerRuntime
    from zhaoxi.workflow.runtime import WorkflowRuntime

logger = logging.getLogger("AGENT")
tool_logger = logging.getLogger("TOOL")
model_logger = logging.getLogger("MODEL")


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
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.context_builder = context_builder
        self.conversation = conversation or Conversation()
        self.max_steps = max_steps
        self.timeout_seconds = timeout_seconds
        self.planner = planner
        self.tool_executor = tool_executor or ToolExecutor(registry)
        self.workflow = workflow
        self.proactive = proactive
        self.proactive_scheduler = proactive_scheduler
        self.proactive_state = proactive_state
        self._pending_permissions: dict[str, PendingAgentInvocation] = {}
        self.cognitive: "CognitiveCoordinator | None" = None

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
            model_response = await asyncio.wait_for(
                self.provider.generate(messages, None), timeout=self.timeout_seconds
            )
            content = (model_response.content or "").strip()
        except Exception as exc:
            logger.warning("workflow final response fallback run=%s error=%s", run.id, type(exc).__name__)
        if not content:
            content = self._workflow_fallback(run)
        self.conversation.add_assistant(content)
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

    async def run(self, user_message: str, *, require_tool_call: bool = False, images: list[str] | None = None) -> AgentResponse:
        """Accept one user turn and return a final natural-language response."""
        if not user_message.strip():
            raise ValueError("消息不能为空。")
        request_id = uuid4().hex
        self.conversation.add_user(user_message.strip(), images=images)
        logger.info("request=%s received user input", request_id)
        memories = []
        if self.context_builder.memory_retriever:
            try:
                memories = await self.context_builder.memory_retriever.retrieve(user_message.strip())
                logger.info("request=%s memory_hits=%d", request_id, len(memories))
            except Exception as exc:
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
                    user_message.strip(),
                    require_tool_call=require_tool_call,
                ),
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            logger.error("request=%s timed out", request_id)
            raise AgentLoopError(f"请求超过 {self.timeout_seconds:g} 秒，已停止。") from exc

    async def run_direct(self, user_message: str) -> AgentResponse:
        """Answer without exposing tools, for turns classified as DIRECT."""
        if not user_message.strip():
            raise ValueError("消息不能为空。")
        request_id = uuid4().hex
        clean_message = user_message.strip()
        self.conversation.add_user(clean_message)
        memories = []
        if self.context_builder.memory_retriever:
            try:
                memories = await self.context_builder.memory_retriever.retrieve(clean_message)
            except Exception as exc:
                log_internal_failure(
                    "request=%s memory retrieval failed; continuing without memory",
                    request_id,
                    exc=exc,
                )
        try:
            response = await asyncio.wait_for(
                self.provider.generate(self.context_builder.build(self.conversation, memories), None),
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            raise AgentLoopError(f"请求超过 {self.timeout_seconds:g} 秒，已停止。") from exc
        except ProviderError as exc:
            log_internal_failure("request=%s provider error", request_id, exc=exc)
            raise AgentLoopError("模型服务当前不可访问，请稍后重试。") from exc
        content = response.content or "模型没有返回可显示的内容。"
        self.conversation.add_assistant(content)
        return AgentResponse(content=content, request_id=request_id, steps=1)

    async def _run_loop(
        self,
        request_id: str,
        memories: list[MemorySearchResult] | None = None,
        user_intent: str = "",
        require_tool_call: bool = False,
    ) -> AgentResponse:
        schemas = self.registry.schemas()
        tool_called = False
        corrective_retry = False
        for step in range(1, self.max_steps + 1):
            model_logger.info("request=%s step=%d calling model", request_id, step)
            try:
                messages = self.context_builder.build(self.conversation, memories)
                if corrective_retry and not tool_called:
                    messages[0].content = (
                        (messages[0].content or "")
                        + "\n本轮用户明确要求真实查询或检查。你上一尝试没有调用工具；"
                        "现在必须调用一个最相关的可用工具，不得只描述将要检查。"
                    )
                response = await self.provider.generate(messages, schemas)
            except ProviderError as exc:
                log_internal_failure("request=%s provider error", request_id, exc=exc)
                raise AgentLoopError(
                    "模型服务当前不可访问，请稍后重试；这次没有执行任何新的工具操作。"
                ) from exc

            if not response.tool_calls:
                if require_tool_call and not tool_called and not corrective_retry:
                    corrective_retry = True
                    logger.warning("request=%s required tool call missing; retrying once", request_id)
                    continue
                if require_tool_call and not tool_called:
                    raise AgentLoopError("这次没有实际完成工具查询，请换一种更明确的说法重试。")
                content = response.content or "模型没有返回可显示的内容。"
                self.conversation.add_assistant(content)
                logger.info("request=%s final response step=%d", request_id, step)
                return AgentResponse(content=content, request_id=request_id, steps=step)

            self.conversation.add_assistant(response.content, tool_calls=response.tool_calls)
            tool_called = True
            for call_index, call in enumerate(response.tool_calls):
                tool_logger.info(
                    "request=%s tool=%s argument_keys=%s",
                    request_id,
                    call.name,
                    sorted(call.arguments),
                )
                execution = await self.tool_executor.execute(
                    call.name,
                    call.arguments,
                    request_id=request_id,
                    origin=InvocationOrigin.AGENT,
                    user_intent=user_intent,
                )
                if execution.waiting_for_permission:
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
                    )
                    return AgentResponse(
                        content=confirmation.question,
                        request_id=request_id,
                        steps=step,
                        permission_confirmation=confirmation,
                    )
                result = execution.result
                self.conversation.add_tool(
                    json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
                    tool_call_id=call.id,
                    name=call.name,
                )
                tool_logger.info("request=%s tool=%s success=%s", request_id, call.name, result.success)

        logger.error("request=%s reached max steps=%d", request_id, self.max_steps)
        raise AgentLoopError(f"已达到最大执行步数（{self.max_steps}），为避免无限循环已停止。")

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
            if position in approved_positions:
                execution = await self.tool_executor.execute(
                    call.name,
                    call.arguments,
                    request_id=pending.request_id,
                    origin=InvocationOrigin.AGENT,
                    user_intent=pending.user_intent,
                    invocation_id=pending.invocation_id if position == 1 else None,
                    approved_batch_confirmation_id=(
                        confirmation_id if position > 1 else None
                    ),
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
            self.conversation.add_tool(
                json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
                tool_call_id=call.id,
                name=call.name,
            )
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
        )
        continued = await self._execute_remaining_calls(tail_pending)
        if continued is not None:
            return continued
        return await self._run_loop(pending.request_id, user_intent=pending.user_intent)

    async def _execute_remaining_calls(
        self,
        pending: PendingAgentInvocation,
    ) -> AgentResponse | None:
        """Finish the untouched tail of a multi-call model response after approval."""
        for index, call in enumerate(pending.remaining_calls):
            execution = await self.tool_executor.execute(
                call.name,
                call.arguments,
                request_id=pending.request_id,
                origin=InvocationOrigin.AGENT,
                user_intent=pending.user_intent,
            )
            if execution.waiting_for_permission:
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
                )
                return AgentResponse(
                    content=confirmation.question,
                    request_id=pending.request_id,
                    steps=0,
                    permission_confirmation=confirmation,
                )
            self.conversation.add_tool(
                json.dumps(execution.result.model_dump(mode="json"), ensure_ascii=False),
                tool_call_id=call.id,
                name=call.name,
            )
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
