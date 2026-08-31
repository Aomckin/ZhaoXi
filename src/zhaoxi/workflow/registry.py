"""Workflow registration and static graph validation."""

from zhaoxi.tools.registry import ToolRegistry
from zhaoxi.workflow.expressions import evaluate
from zhaoxi.workflow.models import WorkflowDefinition, WorkflowStepType


class WorkflowValidationError(ValueError):
    pass


class WorkflowRegistry:
    def __init__(self, tools: ToolRegistry | None = None) -> None:
        self.tools = tools
        self._definitions: dict[tuple[str, int], WorkflowDefinition] = {}

    def register(self, definition: WorkflowDefinition) -> WorkflowDefinition:
        key = (definition.id, definition.version)
        if key in self._definitions:
            raise WorkflowValidationError(f"Workflow 已注册：{definition.id}@{definition.version}")
        self._validate(definition)
        self._definitions[key] = definition
        return definition

    def get(self, workflow_id: str, version: int | None = None) -> WorkflowDefinition:
        matches = [item for (name, _), item in self._definitions.items() if name == workflow_id]
        if version is not None:
            matches = [item for item in matches if item.version == version]
        if not matches:
            raise WorkflowValidationError(f"Workflow 不存在：{workflow_id}")
        value = max(matches, key=lambda item: item.version)
        if not value.enabled:
            raise WorkflowValidationError(f"Workflow 已禁用：{workflow_id}")
        return value

    def list(self) -> list[WorkflowDefinition]:
        return sorted(self._definitions.values(), key=lambda item: (item.id, item.version))

    def _validate(self, definition: WorkflowDefinition) -> None:
        ids = [item.id for item in definition.steps]
        if len(ids) != len(set(ids)):
            raise WorkflowValidationError("Workflow 步骤 ID 不能重复")
        known = set(ids)
        for step in definition.steps:
            targets = [step.next, step.on_true, step.on_false, step.on_failure]
            missing = [item for item in targets if item is not None and item not in known]
            if missing:
                raise WorkflowValidationError(f"步骤 {step.id} 指向不存在的步骤：{missing[0]}")
            if step.type == WorkflowStepType.TOOL and self.tools is not None:
                try:
                    self.tools.get(step.tool or "")
                except Exception as exc:
                    raise WorkflowValidationError(f"步骤 {step.id} 使用未知 Tool：{step.tool}") from exc
            if step.type == WorkflowStepType.CONDITION:
                try:
                    evaluate(step.expression, {})
                except Exception as exc:
                    if "变量不存在" not in str(exc):
                        raise WorkflowValidationError(f"步骤 {step.id} 条件无效：{exc}") from exc
        if not any(item.type == WorkflowStepType.END for item in definition.steps):
            raise WorkflowValidationError("Workflow 至少需要一个 end 步骤")
        self._validate_acyclic(definition)

    @staticmethod
    def _validate_acyclic(definition: WorkflowDefinition) -> None:
        steps = {item.id: item for item in definition.steps}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise WorkflowValidationError("v0.5 不允许 Workflow 定义包含循环")
            if step_id in visited:
                return
            visiting.add(step_id)
            step = steps[step_id]
            targets = [step.next, step.on_true, step.on_false, step.on_failure]
            for target in {item for item in targets if item is not None}:
                visit(target)
            visiting.remove(step_id)
            visited.add(step_id)

        visit(definition.steps[0].id)
        unreachable = set(steps) - visited
        if unreachable:
            raise WorkflowValidationError(
                f"Workflow 包含不可达步骤：{', '.join(sorted(unreachable))}"
            )
