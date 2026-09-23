"""Deterministic control loop for explicit multi-step tasks."""

import asyncio
import copy
import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.core.reply import commit_reply
from zhaoxi.errors import (
    PlanValidationError,
    PlannerLimitError,
    PlannerTaskCancelledError,
    PlannerTimeoutError,
)
from zhaoxi.models.base import ModelProvider
from zhaoxi.models.types import ToolCall
from zhaoxi.planner.models import (
    Goal,
    GoalStatus,
    InputRequest,
    Observation,
    Plan,
    PlanStep,
    StepStatus,
    TERMINAL_GOAL_STATUSES,
)
from zhaoxi.planner.store import InMemoryPlanStore, PlanStore
from zhaoxi.planner.trace import TraceRecorder
from zhaoxi.permission.executor import ToolExecutor
from zhaoxi.permission.models import InvocationOrigin, PendingConfirmation
from zhaoxi.reliability.retry import BudgetExtensionRequest, budget_stage_scope, current_budget
from zhaoxi.tools.base import ToolResult
from zhaoxi.tools.registry import ToolRegistry


class CreatePlanInput(BaseModel):
    steps: list[str] = Field(min_length=1)
    reason: str = "initial plan"


class ReplanInput(BaseModel):
    steps: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1)


class RequestInputInput(BaseModel):
    question: str = Field(min_length=1)
    missing_fields: list[str] = Field(default_factory=list)


class FinishTaskInput(BaseModel):
    summary: str = Field(min_length=1)


class BudgetExtensionInput(BaseModel):
    reason: str = Field(min_length=1, max_length=240)
    remaining_actions: int = Field(ge=0)
    estimated_extra_tokens: int = Field(gt=0)
    stage: str = Field(pattern="^(planning|tool_execution|recovery|finalization)$")
    progress_evidence: dict[str, object] = Field(default_factory=dict)


CONTROL_MODELS = {
    "create_plan": CreatePlanInput,
    "replan": ReplanInput,
    "request_user_input": RequestInputInput,
    "finish_task": FinishTaskInput,
    "request_budget_extension": BudgetExtensionInput,
}

CONTROL_DESCRIPTIONS = {
    "create_plan": "为当前目标创建初始的有序多步计划；开始执行前必须调用一次。",
    "replan": "观察结果使当前计划不再适用时，创建完整的新修订计划。",
    "request_user_input": "缺少继续执行所必需的信息时暂停任务并询问用户。",
    "finish_task": "所有必要步骤完成后，提交最终结果并结束任务。",
    "request_budget_extension": "预算接近上限且已有实际进展时，结构化申请额外 Token；Runtime 独立审批，最多两次。",
}


def control_schemas() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": CONTROL_DESCRIPTIONS[name],
                "parameters": model.model_json_schema(),
            },
        }
        for name, model in CONTROL_MODELS.items()
    ]


@dataclass(slots=True)
class PlannerResponse:
    content: str
    goal_id: str
    status: GoalStatus
    trace_id: str
    steps: int
    input_request: InputRequest | None = None
    permission_confirmation: PendingConfirmation | None = None


@dataclass(slots=True)
class PendingPlannerInvocation:
    goal_id: str
    step_id: str
    tool_call_id: str
    name: str
    arguments: dict[str, object]
    invocation_id: str
    recovered: bool = False


class PlannerRuntime:
    """Execute explicit planned tasks while enforcing deterministic limits."""

    def __init__(
        self,
        *,
        provider: ModelProvider,
        registry: ToolRegistry,
        context_builder: ContextBuilder,
        conversation: Conversation | None = None,
        store: PlanStore | None = None,
        trace: TraceRecorder | None = None,
        max_steps: int = 12,
        max_replans: int = 3,
        max_attempts_per_step: int = 2,
        step_timeout_seconds: float = 30,
        total_timeout_seconds: float = 180,
        tool_executor: ToolExecutor | None = None,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.context_builder = context_builder
        self.conversation = conversation or Conversation()
        self.store = store or InMemoryPlanStore()
        self.trace = trace or TraceRecorder()
        self.max_steps = max_steps
        self.max_replans = max_replans
        self.max_attempts_per_step = max_attempts_per_step
        self.step_timeout_seconds = step_timeout_seconds
        self.total_timeout_seconds = total_timeout_seconds
        self.tool_executor = tool_executor or ToolExecutor(registry)
        self._pending_permissions: dict[str, PendingPlannerInvocation] = {}
        self._cancelled: set[str] = set()
        self._restore_pending_permissions()

    def _restore_pending_permissions(self) -> None:
        """Rebuild resumable permission waits from a persistent PlanStore."""
        for goal in self.store.list_sync():
            confirmation = goal.permission_confirmation
            request = confirmation.request if confirmation is not None else None
            if (
                goal.status is not GoalStatus.WAITING_FOR_PERMISSION
                or confirmation is None
                or confirmation.resolved
                or request is None
                or request.step_id is None
            ):
                continue
            self._pending_permissions[confirmation.confirmation_id] = PendingPlannerInvocation(
                goal_id=goal.id,
                step_id=request.step_id,
                tool_call_id=request.invocation_id,
                name=request.tool_name,
                arguments=copy.deepcopy(request.arguments),
                invocation_id=request.invocation_id,
                recovered=True,
            )

    async def run(self, description: str) -> PlannerResponse:
        if not description.strip():
            raise ValueError("任务目标不能为空。")
        goal = Goal(description=description.strip())
        await self.store.save(goal)
        self.trace.record(goal, "goal_created")
        self.conversation.add_user(description.strip())
        return await self._execute_with_timeout(goal)

    async def resume(self, goal_id: str, answer: str, resume_token: str | None = None) -> PlannerResponse:
        goal = await self._require(goal_id)
        if goal.status != GoalStatus.WAITING_FOR_USER or goal.input_request is None:
            raise PlanValidationError("该任务当前不在等待用户补充信息。")
        if resume_token and resume_token != goal.input_request.resume_token:
            raise PlanValidationError("恢复令牌无效。")
        goal.input_request = None
        goal.transition(GoalStatus.RUNNING if goal.plans else GoalStatus.PLANNING)
        await self.store.save(goal)
        self.conversation.add_user(answer.strip())
        self.trace.record(goal, "task_resumed")
        return await self._execute_with_timeout(goal)

    async def approve_permission(self, confirmation_id: str) -> PlannerResponse:
        pending = self._pending_permissions[confirmation_id]
        goal = await self._require(pending.goal_id)
        if goal.status != GoalStatus.WAITING_FOR_PERMISSION:
            raise PlanValidationError("该任务当前不在等待权限确认。")
        self.tool_executor.gateway.approve(confirmation_id)
        execution = await self.tool_executor.execute(
            pending.name,
            pending.arguments,
            request_id=goal.id,
            origin=InvocationOrigin.PLANNER,
            user_intent=goal.description,
            invocation_id=pending.invocation_id,
            goal_id=goal.id,
            step_id=pending.step_id,
        )
        if execution.result is None:
            raise PlanValidationError("授权未能匹配原始工具调用。")
        step = next(item for item in goal.current_plan.steps if item.id == pending.step_id)
        self._record_observation(goal, step, pending.name, execution.result)
        if execution.result.success:
            step.result_summary = execution.result.content
            step.transition(StepStatus.COMPLETED)
            self.trace.record(goal, "step_completed", step_id=step.id)
        else:
            step.transition(StepStatus.FAILED)
        goal.permission_confirmation = None
        goal.transition(GoalStatus.RUNNING)
        if not pending.recovered:
            self.conversation.add_tool(
                json.dumps(execution.result.model_dump(mode="json"), ensure_ascii=False),
                tool_call_id=pending.tool_call_id,
                name=pending.name,
            )
        del self._pending_permissions[confirmation_id]
        await self.store.save(goal)
        return await self._execute_with_timeout(goal)

    async def deny_permission(self, confirmation_id: str) -> PlannerResponse:
        pending = self._pending_permissions.pop(confirmation_id)
        goal = await self._require(pending.goal_id)
        self.tool_executor.gateway.deny(confirmation_id)
        step = next(item for item in goal.current_plan.steps if item.id == pending.step_id)
        result = ToolResult(success=False, content="用户拒绝了该操作。", error="permission_denied")
        self._record_observation(goal, step, pending.name, result)
        step.transition(StepStatus.FAILED)
        goal.permission_confirmation = None
        goal.transition(GoalStatus.RUNNING)
        if not pending.recovered:
            self.conversation.add_tool(
                json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
                tool_call_id=pending.tool_call_id,
                name=pending.name,
            )
        await self.store.save(goal)
        return await self._execute_with_timeout(goal)

    async def cancel(self, goal_id: str) -> Goal:
        goal = await self._require(goal_id)
        if goal.status in TERMINAL_GOAL_STATUSES:
            return goal
        self._cancelled.add(goal_id)
        for confirmation_id, pending in list(self._pending_permissions.items()):
            if pending.goal_id != goal_id:
                continue
            confirmation = self.tool_executor.gateway.store.pending.get(confirmation_id)
            if confirmation is not None and not confirmation.resolved:
                self.tool_executor.gateway.deny(confirmation_id)
            del self._pending_permissions[confirmation_id]
        goal.permission_confirmation = None
        goal.transition(GoalStatus.CANCELLED)
        if goal.current_plan:
            for step in goal.current_plan.steps:
                if step.status in {StepStatus.PENDING, StepStatus.RUNNING, StepStatus.FAILED}:
                    step.transition(StepStatus.CANCELLED)
        await self.store.save(goal)
        self.trace.record(goal, "task_cancelled")
        return goal

    async def _execute(self, goal: Goal) -> PlannerResponse:
        if goal.status == GoalStatus.PENDING:
            goal.transition(GoalStatus.PLANNING)
            await self.store.save(goal)
        memories = []
        if self.context_builder.memory_retriever:
            try:
                memories = await self.context_builder.memory_retriever.retrieve(goal.description)
            except Exception:
                memories = []
        schemas = [*control_schemas(), *(tool.schema() for tool in self.registry.list())]
        for action_index in range(1, self.max_steps + 1):
            self._check_cancelled(goal)
            plan = goal.current_plan
            remaining = [step for step in plan.steps if step.status not in {StepStatus.COMPLETED, StepStatus.SKIPPED}] if plan else []
            completed = [step for step in plan.steps if step.status is StepStatus.COMPLETED] if plan else []
            finalizing = bool(plan and not remaining)
            stage = "finalization" if finalizing else "tool_execution" if plan else "planning"
            budget = current_budget()
            if budget and budget.policy and budget.extension_count < 2 and completed:
                threshold = (budget.max_total_tokens - budget.finalization_reserve) * budget.policy.warning_ratio
                if budget.total_tokens >= threshold and (not finalizing or budget.total_tokens >= budget.max_total_tokens):
                    limit = budget.policy.extension_1_limit if budget.extension_count == 0 else budget.policy.extension_2_limit
                    if limit > 0 and (budget.extension_count == 0 or finalizing or len(remaining) <= 1):
                        budget.request_extension(BudgetExtensionRequest(
                            reason="计划仍有明确步骤或需要收尾", remaining_actions=len(remaining),
                            estimated_extra_tokens=limit, stage=stage,
                            progress_evidence={"completed_actions": len(completed),
                                               "last_success_step": action_index - 1,
                                               "corrective_retry": bool(goal.observations and not goal.observations[-1].success
                                                                        and goal.observations[-1].retryable),
                                               "stalled_rounds": max(0, action_index - len(goal.observations) - 1),
                                               "remaining_actions_verified": True},
                        ))
            messages = self.context_builder.build(
                self.conversation,
                memories,
                planner_context=self._format_state(goal),
                **({"release_images": True} if finalizing else {}),
            )
            if finalizing:
                messages[0].content = (messages[0].content or "") + "\n计划步骤已完成，只生成最终自然语言回复，不再调用工具。"
            with budget_stage_scope(stage):
                response = await self.provider.generate(messages, None if finalizing else schemas)
            self._check_cancelled(goal)
            if not response.tool_calls:
                if goal.current_plan and all(
                    step.status in {StepStatus.COMPLETED, StepStatus.SKIPPED}
                    for step in goal.current_plan.steps
                ):
                    sequence, _ = commit_reply(
                        self.conversation,
                        response.content or "任务已完成。",
                        getattr(self.context_builder, "emoji_service", None),
                    )
                    return await self._finish(goal, sequence.visible_text, action_index)
                self.conversation.add_assistant(response.content)
                continue

            self.conversation.add_assistant(response.content, tool_calls=response.tool_calls)
            for call in response.tool_calls:
                result = await self._handle_call(goal, call)
                if goal.status == GoalStatus.WAITING_FOR_USER:
                    self.conversation.add_tool(
                        json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
                        tool_call_id=call.id,
                        name=call.name,
                    )
                    await self.store.save(goal)
                    return self._response(goal, goal.input_request.question, action_index)
                if goal.status == GoalStatus.WAITING_FOR_PERMISSION:
                    await self.store.save(goal)
                    return self._response(
                        goal, goal.permission_confirmation.question, action_index
                    )
                self.conversation.add_tool(
                    json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
                    tool_call_id=call.id,
                    name=call.name,
                )
                if goal.status == GoalStatus.COMPLETED:
                    return self._response(goal, goal.final_content or "任务已完成。", action_index)
            await self.store.save(goal)
        goal = await self._require(goal.id)
        if goal.status not in TERMINAL_GOAL_STATUSES:
            goal.transition(GoalStatus.FAILED)
            await self.store.save(goal)
            self.trace.record(goal, "task_failed", metadata={"reason": "max_steps"})
        raise PlannerLimitError(f"已达到规划任务最大执行步数（{self.max_steps}）。")

    async def _execute_with_timeout(self, goal: Goal) -> PlannerResponse:
        try:
            return await asyncio.wait_for(self._execute(goal), timeout=self.total_timeout_seconds)
        except TimeoutError as exc:
            await self._fail_if_active(goal.id, "total_timeout")
            raise PlannerTimeoutError(
                f"规划任务超过 {self.total_timeout_seconds:g} 秒，已停止。"
            ) from exc
        except PlannerTaskCancelledError:
            raise
        except Exception as exc:
            await self._fail_if_active(goal.id, type(exc).__name__)
            raise

    async def _fail_if_active(self, goal_id: str, reason: str) -> None:
        goal = await self._require(goal_id)
        if goal.status not in TERMINAL_GOAL_STATUSES:
            goal.transition(GoalStatus.FAILED)
            await self.store.save(goal)
            self.trace.record(goal, "task_failed", metadata={"reason": reason})

    async def _handle_call(self, goal: Goal, call: ToolCall) -> ToolResult:
        if call.name in CONTROL_MODELS:
            return await self._handle_control(goal, call)
        if not goal.current_plan:
            return ToolResult(success=False, content="必须先创建计划。", error="plan_required")
        if goal.status == GoalStatus.PLANNING:
            goal.transition(GoalStatus.RUNNING)
        step = self._current_step(goal)
        if step is None:
            return ToolResult(success=False, content="计划步骤已全部处理，请结束任务。", error="finish_required")
        if step.status == StepStatus.FAILED and step.tool_attempts and call.name not in step.tool_attempts:
            self.trace.record(
                goal,
                "fallback_selected",
                step_id=step.id,
                metadata={"tool": call.name},
            )
        if step.status == StepStatus.FAILED:
            step.transition(StepStatus.PENDING)
        if step.status == StepStatus.PENDING:
            step.transition(StepStatus.RUNNING)
        self.trace.record(goal, "step_started", step_id=step.id)
        last_result = ToolResult(success=False, content="工具尚未执行。")
        tool_attempts = step.tool_attempts.get(call.name, 0)
        while tool_attempts < self.max_attempts_per_step:
            self._check_cancelled(goal)
            tool_attempts += 1
            step.attempt_count += 1
            step.tool_attempts[call.name] = tool_attempts
            self.trace.record(
                goal,
                "tool_called",
                step_id=step.id,
                metadata={"tool": call.name, "attempt": step.attempt_count},
            )
            execution = await self._execute_tool(goal, call)
            if execution.waiting_for_permission:
                confirmation = execution.confirmation
                goal.permission_confirmation = confirmation
                goal.transition(GoalStatus.WAITING_FOR_PERMISSION)
                self._pending_permissions[confirmation.confirmation_id] = PendingPlannerInvocation(
                    goal_id=goal.id,
                    step_id=step.id,
                    tool_call_id=call.id,
                    name=call.name,
                    arguments=copy.deepcopy(call.arguments),
                    invocation_id=execution.request.invocation_id,
                )
                self.trace.record(goal, "permission_requested", step_id=step.id)
                return ToolResult(
                    success=False,
                    content=confirmation.question,
                    error="confirmation_required",
                )
            last_result = execution.result
            retryable = bool(last_result.metadata.get("retryable", False))
            observation = Observation(
                step_id=step.id,
                tool_name=call.name,
                success=last_result.success,
                content=last_result.content,
                data=last_result.data,
                error=last_result.error,
                retryable=retryable,
            )
            goal.observations.append(observation)
            self.trace.record(
                goal,
                "observation_received",
                step_id=step.id,
                metadata={"tool": call.name, "success": last_result.success, "retryable": retryable},
            )
            if last_result.success:
                step.result_summary = last_result.content
                step.transition(StepStatus.COMPLETED)
                self.trace.record(goal, "step_completed", step_id=step.id)
                break
            if not retryable or tool_attempts >= self.max_attempts_per_step:
                step.transition(StepStatus.FAILED)
                break
            self.trace.record(goal, "step_retried", step_id=step.id)
        return last_result

    def _record_observation(
        self, goal: Goal, step: PlanStep, tool_name: str, result: ToolResult
    ) -> None:
        retryable = bool(result.metadata.get("retryable", False))
        goal.observations.append(Observation(
            step_id=step.id,
            tool_name=tool_name,
            success=result.success,
            content=result.content,
            data=result.data,
            error=result.error,
            retryable=retryable,
        ))
        self.trace.record(
            goal,
            "observation_received",
            step_id=step.id,
            metadata={"tool": tool_name, "success": result.success, "retryable": retryable},
        )

    async def _handle_control(self, goal: Goal, call: ToolCall) -> ToolResult:
        try:
            arguments = CONTROL_MODELS[call.name].model_validate(call.arguments)
        except ValidationError as exc:
            return ToolResult(success=False, content="规划控制参数无效。", error=str(exc))
        if call.name == "request_budget_extension":
            budget = current_budget()
            if budget is None:
                return ToolResult(success=False, content="当前没有可扩容的请求预算。", error="budget_scope_unavailable")
            plan = goal.current_plan
            remaining = [step for step in plan.steps if step.status not in {StepStatus.COMPLETED, StepStatus.SKIPPED}] if plan else []
            completed = [step for step in plan.steps if step.status is StepStatus.COMPLETED] if plan else []
            recent_errors = [observation.error for observation in goal.observations[-3:] if not observation.success]
            request = BudgetExtensionRequest(
                reason=arguments.reason, remaining_actions=arguments.remaining_actions,
                estimated_extra_tokens=arguments.estimated_extra_tokens, stage=arguments.stage,
                progress_evidence={"completed_actions": len(completed),
                                   "last_success_step": len(completed) or None,
                                   "new_result": bool(goal.observations and goal.observations[-1].success),
                                   "corrective_retry": bool(goal.observations and not goal.observations[-1].success
                                                            and goal.observations[-1].retryable),
                                   "repeated_error_count": len(recent_errors) if len(set(recent_errors)) == 1 else 0,
                                   "remaining_actions_verified": arguments.remaining_actions == len(remaining)},
            )
            decision = budget.request_extension(request)
            return ToolResult(success=bool(decision["approved_extra"]),
                              content="额外预算已批准。" if decision["approved_extra"] else "额外预算申请未通过。",
                              data=decision,
                              error=None if decision["approved_extra"] else str(decision["reason_code"]))
        if call.name == "create_plan":
            if goal.plans:
                return ToolResult(success=False, content="初始计划已存在，请使用 replan。", error="plan_exists")
            value = arguments
            plan = Plan(
                goal_id=goal.id,
                revision=1,
                steps=[PlanStep(description=item) for item in value.steps],
                reason=value.reason,
            )
            goal.plans.append(plan)
            goal.transition(GoalStatus.RUNNING)
            self.trace.record(goal, "plan_created", metadata={"step_count": len(plan.steps)})
            return ToolResult(success=True, content="计划已创建。", data=plan.model_dump(mode="json"))
        if call.name == "replan":
            if not goal.plans:
                return ToolResult(success=False, content="尚无初始计划。", error="plan_required")
            if goal.replan_count >= self.max_replans:
                return ToolResult(success=False, content="已达到重新规划次数上限。", error="replan_limit")
            value = arguments
            for step in goal.current_plan.steps:
                if step.status in {StepStatus.PENDING, StepStatus.FAILED}:
                    step.transition(StepStatus.SKIPPED)
            goal.replan_count += 1
            plan = Plan(
                goal_id=goal.id,
                revision=goal.current_plan.revision + 1,
                steps=[PlanStep(description=item) for item in value.steps],
                reason=value.reason,
            )
            goal.plans.append(plan)
            self.trace.record(goal, "plan_revised", metadata={"reason": value.reason})
            return ToolResult(success=True, content="计划已重新修订。", data=plan.model_dump(mode="json"))
        if call.name == "request_user_input":
            value = arguments
            request = InputRequest(
                goal_id=goal.id,
                question=value.question,
                missing_fields=value.missing_fields,
            )
            goal.input_request = request
            goal.transition(GoalStatus.WAITING_FOR_USER)
            self.trace.record(goal, "input_requested", metadata={"missing_fields": value.missing_fields})
            return ToolResult(success=True, content=value.question, data=request.model_dump(mode="json"))
        value = arguments
        return await self._finish_result(goal, value.summary)

    async def _finish_result(self, goal: Goal, summary: str) -> ToolResult:
        incomplete = []
        if goal.current_plan:
            incomplete = [
                step.description
                for step in goal.current_plan.steps
                if step.status not in {StepStatus.COMPLETED, StepStatus.SKIPPED}
            ]
        if incomplete:
            return ToolResult(
                success=False,
                content="仍有未完成步骤，不能结束任务。",
                error="incomplete_steps",
                data={"steps": incomplete},
            )
        goal.final_content = summary
        goal.transition(GoalStatus.COMPLETED)
        self.trace.record(goal, "task_completed")
        await self.store.save(goal)
        return ToolResult(success=True, content=summary)

    async def _finish(self, goal: Goal, content: str, steps: int) -> PlannerResponse:
        result = await self._finish_result(goal, content)
        if not result.success:
            raise PlanValidationError(result.content)
        return self._response(goal, content, steps)

    async def _execute_tool(self, goal: Goal, call: ToolCall):
        try:
            return await asyncio.wait_for(
                self.tool_executor.execute(
                    call.name,
                    call.arguments,
                    request_id=goal.id,
                    origin=InvocationOrigin.PLANNER,
                    user_intent=goal.description,
                    goal_id=goal.id,
                    step_id=self._current_step(goal).id if self._current_step(goal) else None,
                ),
                timeout=self.step_timeout_seconds,
            )
        except TimeoutError:
            from zhaoxi.permission.executor import ToolExecution
            return ToolExecution(
                ToolResult(
                    success=False,
                    content="工具执行超时。",
                    error="step_timeout",
                    metadata={"retryable": True},
                )
            )

    def _current_step(self, goal: Goal) -> PlanStep | None:
        if not goal.current_plan:
            return None
        return next(
            (step for step in goal.current_plan.steps if step.status in {StepStatus.PENDING, StepStatus.RUNNING, StepStatus.FAILED}),
            None,
        )

    def _format_state(self, goal: Goal) -> str:
        state = goal.model_dump(mode="json", exclude={"observations": True})
        state["recent_observations"] = [
            item.model_dump(mode="json") for item in goal.observations[-6:]
        ]
        state["rules"] = (
            "先 create_plan；每个业务工具调用对应当前步骤；失败后可换用已注册工具或 replan；"
            "信息不足用 request_user_input；所有步骤完成后用 finish_task。"
        )
        return json.dumps(state, ensure_ascii=False)

    def _check_cancelled(self, goal: Goal) -> None:
        if goal.id in self._cancelled or goal.status == GoalStatus.CANCELLED:
            raise PlannerTaskCancelledError("任务已取消。")

    async def _require(self, goal_id: str) -> Goal:
        if isinstance(self.store, InMemoryPlanStore):
            return await self.store.require(goal_id)
        goal = await self.store.get(goal_id)
        if goal is None:
            from zhaoxi.errors import PlannerTaskNotFoundError

            raise PlannerTaskNotFoundError(f"没有找到任务 {goal_id}。")
        return goal

    def _response(self, goal: Goal, content: str, steps: int) -> PlannerResponse:
        return PlannerResponse(
            content=content,
            goal_id=goal.id,
            status=goal.status,
            trace_id=self.trace.trace_id_for(goal.id),
            steps=steps,
            input_request=goal.input_request,
            permission_confirmation=goal.permission_confirmation,
        )
