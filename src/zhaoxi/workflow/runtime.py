"""Deterministic workflow state machine."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from zhaoxi.permission.executor import ToolExecutor
from zhaoxi.errors import ZhaoxiError
from zhaoxi.permission.models import InvocationOrigin
from zhaoxi.workflow.expressions import resolve_path, resolve_value, evaluate
from zhaoxi.workflow.models import (
    TERMINAL_WORKFLOW_STATUSES,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowStatus,
    WorkflowStep,
    WorkflowStepRun,
    WorkflowStepStatus,
    WorkflowStepType,
    utc_now,
)
from zhaoxi.workflow.registry import WorkflowRegistry
from zhaoxi.workflow.store import InMemoryWorkflowStore, WorkflowStore


class WorkflowRuntimeError(ZhaoxiError):
    def __init__(self, message: str, *, user_message: str | None = None) -> None:
        super().__init__(message)
        self.trace_id = uuid4().hex
        self.user_message = user_message or "这个流程暂时无法继续，请检查输入后再试。"


class WorkflowRuntime:
    def __init__(
        self,
        registry: WorkflowRegistry,
        tool_executor: ToolExecutor,
        store: WorkflowStore | None = None,
        *,
        max_steps: int = 50,
        max_events: int = 200,
    ) -> None:
        self.registry = registry
        self.tool_executor = tool_executor
        self.store = store or InMemoryWorkflowStore()
        self.max_steps = max_steps
        self.max_events = max_events

    async def start(
        self,
        workflow_id: str,
        inputs: dict[str, Any] | None = None,
        *,
        version: int | None = None,
        user_intent: str = "",
    ) -> WorkflowRun:
        definition = self.registry.get(workflow_id, version)
        supplied = dict(inputs or {})
        normalized, missing, ignored = self._validate_inputs(definition, supplied)
        run = WorkflowRun(
            workflow_id=definition.id,
            workflow_version=definition.version,
            user_intent=user_intent,
            definition_snapshot=definition.model_copy(deep=True),
            inputs=normalized,
            ignored_inputs=ignored,
            step_runs=[WorkflowStepRun(step_id=item.id) for item in definition.steps],
        )
        run.record("run_created")
        if ignored:
            run.record("unknown_inputs_ignored", fields=ignored)
        if missing:
            run.status = WorkflowStatus.WAITING_FOR_INPUT
            run.pending_fields = missing
            run.pending_question = f"请补充：{', '.join(missing)}"
            run.record("input_requested", fields=missing)
            await self._save(run)
            return run
        run.status = WorkflowStatus.RUNNING
        run.current_step_id = definition.steps[0].id
        run.record("run_started")
        await self._save(run)
        return await self._advance(run)

    async def provide_input(self, run_id: str, values: dict[str, Any]) -> WorkflowRun:
        run = await self._require(run_id)
        if run.status != WorkflowStatus.WAITING_FOR_INPUT:
            raise WorkflowRuntimeError("该 Workflow 当前不等待输入。")
        run.inputs.update(values)
        normalized, missing, ignored = self._validate_inputs(run.definition_snapshot, run.inputs)
        run.inputs = normalized
        if ignored:
            run.ignored_inputs = sorted(set(run.ignored_inputs) | set(ignored))
            run.record("unknown_inputs_ignored", fields=ignored)
        if missing:
            run.pending_fields = missing
            run.pending_question = f"请补充：{', '.join(missing)}"
            await self._save(run)
            return run
        run.pending_fields = []
        run.pending_question = None
        if run.current_step_id is not None:
            step_run = run.step_run(run.current_step_id)
            if step_run.status == WorkflowStepStatus.WAITING:
                step_run.status = WorkflowStepStatus.COMPLETED
                step_run.finished_at = utc_now()
                current = self._step(run, run.current_step_id)
                run.current_step_id = self._next_id(run.definition_snapshot, current)
        else:
            run.current_step_id = run.definition_snapshot.steps[0].id
        run.status = WorkflowStatus.RUNNING
        run.record("input_received")
        await self._save(run)
        return await self._advance(run)

    async def approve(self, run_id: str) -> WorkflowRun:
        run = await self._require(run_id)
        if run.status != WorkflowStatus.WAITING_FOR_PERMISSION or run.current_step_id is None:
            raise WorkflowRuntimeError("该 Workflow 当前不等待权限确认。")
        step = self._step(run, run.current_step_id)
        step_run = run.step_run(step.id)
        if not step_run.confirmation_id or not step_run.invocation_id:
            raise WorkflowRuntimeError("等待中的权限调用不完整。")
        if step_run.confirmation_id not in self.tool_executor.gateway.store.pending:
            context = self._context(run)
            arguments = self._resolve(step.arguments, context)
            recreated = await self.tool_executor.execute(
                step.tool or "",
                arguments,
                request_id=run.id,
                origin=InvocationOrigin.WORKFLOW,
                invocation_id=step_run.invocation_id,
                step_id=step.id,
                user_intent=run.workflow_id,
            )
            if not recreated.waiting_for_permission:
                raise WorkflowRuntimeError("无法恢复原权限确认。")
            step_run.confirmation_id = recreated.confirmation.confirmation_id
            run.record("permission_recreated", step.id)
        self.tool_executor.gateway.approve(step_run.confirmation_id)
        run.status = WorkflowStatus.RUNNING
        run.record("permission_approved", step.id)
        await self._save(run)
        return await self._execute_tool_step(run, step, approved=True)

    async def deny(self, run_id: str) -> WorkflowRun:
        run = await self._require(run_id)
        if run.status != WorkflowStatus.WAITING_FOR_PERMISSION or run.current_step_id is None:
            raise WorkflowRuntimeError("该 Workflow 当前不等待权限确认。")
        step = self._step(run, run.current_step_id)
        step_run = run.step_run(step.id)
        if step_run.confirmation_id:
            if step_run.confirmation_id in self.tool_executor.gateway.store.pending:
                self.tool_executor.gateway.deny(step_run.confirmation_id)
        step_run.status = WorkflowStepStatus.FAILED
        step_run.error = "permission_denied"
        step_run.finished_at = utc_now()
        run.record("permission_denied", step.id)
        if step.on_failure:
            run.status = WorkflowStatus.RUNNING
            run.current_step_id = step.on_failure
            await self._save(run)
            return await self._advance(run)
        return await self._finish(run, WorkflowStatus.FAILED, error="permission_denied")

    async def pause(self, run_id: str) -> WorkflowRun:
        run = await self._require(run_id)
        if run.status != WorkflowStatus.RUNNING:
            raise WorkflowRuntimeError("只有运行中的 Workflow 可以暂停。")
        run.status = WorkflowStatus.PAUSED
        run.record("run_paused")
        await self._save(run)
        return run

    async def resume(self, run_id: str) -> WorkflowRun:
        run = await self._require(run_id)
        if run.status != WorkflowStatus.PAUSED:
            raise WorkflowRuntimeError("只有主动暂停的 Workflow 可以恢复。")
        run.status = WorkflowStatus.RUNNING
        run.record("run_resumed")
        await self._save(run)
        return await self._advance(run)

    async def cancel(self, run_id: str) -> WorkflowRun:
        run = await self._require(run_id)
        if run.status in TERMINAL_WORKFLOW_STATUSES:
            return run
        if run.status == WorkflowStatus.WAITING_FOR_PERMISSION and run.current_step_id:
            confirmation_id = run.step_run(run.current_step_id).confirmation_id
            if confirmation_id:
                if confirmation_id in self.tool_executor.gateway.store.pending:
                    self.tool_executor.gateway.deny(confirmation_id)
        for step_run in run.step_runs:
            if step_run.status in {WorkflowStepStatus.PENDING, WorkflowStepStatus.WAITING}:
                step_run.status = WorkflowStepStatus.CANCELLED
        return await self._finish(run, WorkflowStatus.CANCELLED)

    async def get(self, run_id: str) -> WorkflowRun:
        return await self._require(run_id)

    async def history(self, limit: int = 100) -> list[WorkflowRun]:
        return await self.store.list(limit)

    async def _advance(self, run: WorkflowRun) -> WorkflowRun:
        count = 0
        while run.status == WorkflowStatus.RUNNING and run.current_step_id is not None:
            count += 1
            if count > self.max_steps:
                return await self._finish(run, WorkflowStatus.FAILED, error="max_steps")
            step = self._step(run, run.current_step_id)
            step_run = run.step_run(step.id)
            if step_run.status == WorkflowStepStatus.COMPLETED:
                run.current_step_id = self._next_id(run.definition_snapshot, step)
                continue
            if step.type == WorkflowStepType.TOOL:
                return await self._execute_tool_step(run, step)
            step_run.status = WorkflowStepStatus.RUNNING
            step_run.started_at = step_run.started_at or utc_now()
            run.record("step_started", step.id)
            context = self._context(run)
            try:
                if step.type == WorkflowStepType.CONDITION:
                    branch = step.on_true if evaluate(step.expression, context) else step.on_false
                    step_run.output = {"branch": bool(branch == step.on_true)}
                    run.current_step_id = branch
                elif step.type == WorkflowStepType.ASK:
                    missing = [name for name in step.fields if run.inputs.get(name) is None]
                    if missing:
                        step_run.status = WorkflowStepStatus.WAITING
                        run.status = WorkflowStatus.WAITING_FOR_INPUT
                        run.pending_fields = missing
                        run.pending_question = step.question
                        run.record("input_requested", step.id, fields=missing)
                        await self._save(run)
                        return run
                    run.current_step_id = self._next_id(run.definition_snapshot, step)
                elif step.type == WorkflowStepType.SET:
                    resolved = self._resolve(step.values, context)
                    run.variables.update(resolved)
                    step_run.output = resolved
                    run.current_step_id = self._next_id(run.definition_snapshot, step)
                elif step.type == WorkflowStepType.END:
                    result = self._resolve(step.result, context)
                    run.result = result
                    step_run.output = result
                    step_run.status = WorkflowStepStatus.COMPLETED
                    step_run.finished_at = utc_now()
                    return await self._finish(run, WorkflowStatus.COMPLETED)
            except Exception as exc:
                step_run.status = WorkflowStepStatus.FAILED
                step_run.error = str(exc)
                step_run.finished_at = utc_now()
                run.record("step_failed", step.id, error=type(exc).__name__)
                if step.on_failure:
                    run.current_step_id = step.on_failure
                    continue
                return await self._finish(run, WorkflowStatus.FAILED, error=str(exc))
            if step_run.status == WorkflowStepStatus.RUNNING:
                step_run.status = WorkflowStepStatus.COMPLETED
                step_run.finished_at = utc_now()
                run.record("step_completed", step.id)
            await self._save(run)
        if run.status == WorkflowStatus.RUNNING:
            return await self._finish(run, WorkflowStatus.FAILED, error="workflow_ended_without_end")
        return run

    async def _execute_tool_step(
        self, run: WorkflowRun, step: WorkflowStep, *, approved: bool = False
    ) -> WorkflowRun:
        step_run = run.step_run(step.id)
        context = self._context(run)
        try:
            arguments = self._resolve(step.arguments, context)
        except Exception as exc:
            return await self._tool_failed(run, step, str(exc))
        step_run.status = WorkflowStepStatus.RUNNING
        step_run.started_at = step_run.started_at or utc_now()
        step_run.attempts += 1
        step_run.invocation_id = step_run.invocation_id or uuid4().hex
        run.record("tool_called", step.id, tool=step.tool, attempt=step_run.attempts)
        execution = await self.tool_executor.execute(
            step.tool or "",
            arguments,
            request_id=run.id,
            origin=InvocationOrigin.WORKFLOW,
            invocation_id=step_run.invocation_id,
            step_id=step.id,
            user_intent=run.workflow_id,
        )
        if execution.waiting_for_permission:
            step_run.status = WorkflowStepStatus.WAITING
            step_run.confirmation_id = execution.confirmation.confirmation_id
            run.status = WorkflowStatus.WAITING_FOR_PERMISSION
            run.record("permission_requested", step.id, confirmation_id=step_run.confirmation_id)
            await self._save(run)
            return run
        result = execution.result
        if result is None:
            return await self._tool_failed(run, step, "missing_tool_result")
        step_run.output = result.model_dump(mode="json")
        if result.success:
            try:
                context = self._context(run)
                for name, path in step.output_mapping.items():
                    run.variables[name] = resolve_path(context, path)
            except Exception as exc:
                return await self._tool_failed(run, step, str(exc))
            step_run.status = WorkflowStepStatus.COMPLETED
            step_run.finished_at = utc_now()
            run.record("step_completed", step.id)
            run.current_step_id = self._next_id(run.definition_snapshot, step)
            run.status = WorkflowStatus.RUNNING
            await self._save(run)
            return await self._advance(run)
        retryable = bool(result.metadata.get("retryable", False))
        if retryable and step_run.attempts < step.retry.max_attempts:
            step_run.invocation_id = None
            step_run.confirmation_id = None
            step_run.status = WorkflowStepStatus.PENDING
            run.record("step_retried", step.id)
            await self._save(run)
            return await self._execute_tool_step(run, step)
        return await self._tool_failed(run, step, result.error or result.content)

    async def _tool_failed(self, run: WorkflowRun, step: WorkflowStep, error: str) -> WorkflowRun:
        step_run = run.step_run(step.id)
        step_run.status = WorkflowStepStatus.FAILED
        step_run.error = error
        step_run.finished_at = utc_now()
        run.record("step_failed", step.id, error=error[:200])
        if step.on_failure:
            run.status = WorkflowStatus.RUNNING
            run.current_step_id = step.on_failure
            await self._save(run)
            return await self._advance(run)
        return await self._finish(run, WorkflowStatus.FAILED, error=error)

    async def _finish(
        self, run: WorkflowRun, status: WorkflowStatus, *, error: str | None = None
    ) -> WorkflowRun:
        run.status = status
        run.error = error
        run.finished_at = utc_now()
        run.record(f"run_{status.value}")
        await self._save(run)
        return run

    def _validate_inputs(
        self, definition: WorkflowDefinition, supplied: dict[str, Any]
    ) -> tuple[dict[str, Any], list[str], list[str]]:
        unknown = sorted(set(supplied) - set(definition.inputs))
        normalized: dict[str, Any] = {}
        missing: list[str] = []
        adapters = {"string": str, "integer": int, "number": float, "boolean": bool, "array": list, "object": dict}
        for name, schema in definition.inputs.items():
            value = supplied.get(name, schema.default)
            if value is None:
                if schema.required:
                    missing.append(name)
                normalized[name] = None
                continue
            try:
                normalized[name] = TypeAdapter(adapters.get(schema.type, Any)).validate_python(value)
            except ValidationError as exc:
                raise WorkflowRuntimeError(
                    f"Workflow 参数 {name} 类型无效。",
                    user_message=f"流程参数“{name}”格式不正确，请换一种说法再试。",
                ) from exc
        return normalized, missing, unknown

    def _context(self, run: WorkflowRun) -> dict[str, Any]:
        return {
            "inputs": run.inputs,
            "variables": run.variables,
            "steps": {item.step_id: {"output": item.output, "status": item.status.value} for item in run.step_runs},
        }

    def _resolve(self, value: Any, context: dict[str, Any]) -> Any:
        if isinstance(value, dict):
            return {key: self._resolve(item, context) for key, item in value.items()}
        if isinstance(value, list):
            return [self._resolve(item, context) for item in value]
        return resolve_value(value, context)

    @staticmethod
    def _step(run: WorkflowRun, step_id: str) -> WorkflowStep:
        try:
            return next(item for item in run.definition_snapshot.steps if item.id == step_id)
        except StopIteration as exc:
            raise WorkflowRuntimeError(f"Workflow 步骤不存在：{step_id}") from exc

    @staticmethod
    def _next_id(definition: WorkflowDefinition, step: WorkflowStep) -> str | None:
        if step.next:
            return step.next
        index = next(i for i, item in enumerate(definition.steps) if item.id == step.id)
        return definition.steps[index + 1].id if index + 1 < len(definition.steps) else None

    async def _require(self, run_id: str) -> WorkflowRun:
        run = await self.store.get(run_id)
        if run is None:
            raise WorkflowRuntimeError(f"Workflow Run 不存在：{run_id}")
        return run

    async def _save(self, run: WorkflowRun) -> None:
        if len(run.events) > self.max_events:
            run.events = run.events[-self.max_events :]
        run.updated_at = utc_now()
        await self.store.save(run)
