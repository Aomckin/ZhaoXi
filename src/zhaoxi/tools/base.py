"""Tool contracts and safe execution."""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from zhaoxi.permission.models import PermissionLevel, SideEffect


class ToolResult(BaseModel):
    """Normalized outcome of a tool invocation."""

    success: bool
    content: str
    data: Any = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Tool(ABC):
    """Base class for tools discoverable by the runtime."""

    name: str
    description: str
    input_model: type[BaseModel]
    permission: PermissionLevel = PermissionLevel.READ
    side_effects: frozenset[SideEffect] = frozenset({SideEffect.NONE})

    @property
    def mutates_state(self) -> bool:
        """Compatibility view for v0.3 callers."""
        return self.permission != PermissionLevel.READ

    def resource_scope(self, arguments: dict[str, Any]) -> str:
        """Return a redacted scope, never raw content."""
        for key in ("memory_id", "path", "event_id", "message_id"):
            if value := arguments.get(key):
                return f"{key}:{value}"
        if values := arguments.get("memory_ids"):
            return f"memory_ids:{','.join(str(item) for item in values)}"
        return self.name

    def confirmation_description(self, arguments: dict[str, Any]) -> str:
        return self.description.split("。", 1)[0]

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_model.model_json_schema(),
            },
        }

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        """Validate arguments and convert all failures into ToolResult."""
        try:
            validated = self.input_model.model_validate(arguments)
        except ValidationError as exc:
            return ToolResult(success=False, content="工具参数无效。", error=str(exc))
        try:
            return await self.execute(validated)
        except Exception as exc:  # tool boundary must protect the agent loop
            return ToolResult(success=False, content="工具执行失败。", error=str(exc))

    @abstractmethod
    async def execute(self, arguments: BaseModel) -> ToolResult:
        """Execute already validated arguments."""
