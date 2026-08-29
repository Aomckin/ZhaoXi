"""Tool contracts and safe execution."""

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field, ValidationError


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
    mutates_state: bool = False

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
