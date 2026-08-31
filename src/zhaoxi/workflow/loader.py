"""YAML workflow loading."""

from pathlib import Path

import yaml
from pydantic import ValidationError

from zhaoxi.workflow.models import WorkflowDefinition


class WorkflowLoadError(ValueError):
    pass


class WorkflowLoader:
    def load_file(self, path: str | Path) -> WorkflowDefinition:
        value = Path(path)
        try:
            payload = yaml.safe_load(value.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise WorkflowLoadError(f"无法读取 Workflow：{value}") from exc
        try:
            return WorkflowDefinition.model_validate(payload)
        except ValidationError as exc:
            raise WorkflowLoadError(f"Workflow 定义无效：{value}\n{exc}") from exc

    def load_directory(self, path: str | Path) -> list[WorkflowDefinition]:
        root = Path(path)
        if not root.exists():
            return []
        return [self.load_file(item) for item in sorted(root.rglob("*.yaml"))]
