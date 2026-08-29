from pydantic import BaseModel, Field

from zhaoxi.tools.base import Tool, ToolResult


class EchoInput(BaseModel):
    message: str = Field(description="要原样返回的文字")


class EchoTool(Tool):
    name = "echo"
    description = "原样返回输入，用于验证工具调用。"
    input_model = EchoInput

    async def execute(self, arguments: EchoInput) -> ToolResult:
        return ToolResult(success=True, content=arguments.message, data={"message": arguments.message})

