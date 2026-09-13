"""Isolated Core for browser acceptance; no model or real tool calls."""

from pathlib import Path
import tempfile

from pydantic import BaseModel
import uvicorn

from zhaoxi.config.settings import Settings
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.models.base import ModelProvider
from zhaoxi.models.types import ModelResponse
from zhaoxi.tools.base import Tool, ToolResult
from zhaoxi.tools.builtin import create_builtin_tools
from zhaoxi.tools.registry import ToolRegistry
from zhaoxi.web.app import create_app


class Provider(ModelProvider):
    async def generate(self, messages, tools=None, **kwargs):
        return ModelResponse(content="本地验收")


class EmptyInput(BaseModel):
    pass


class PreviewTool(Tool):
    name = "job_application_preview"
    group = "job_application"
    source = "local-preview"
    description = "检查网申表单的本地演示钥匙"
    default_enabled = False
    input_model = EmptyInput

    async def execute(self, arguments):
        return ToolResult(success=True, content="演示")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="zhaoxi-tool-ui-") as temporary:
        registry = ToolRegistry(Path(temporary) / "tool_overrides.json")
        for tool in [*create_builtin_tools(), PreviewTool()]:
            registry.register(tool)
        agent = ZhaoxiAgent(provider=Provider(), registry=registry, context_builder=ContextBuilder("朝汐"))
        app = create_app(agent=agent, settings=Settings(_env_file=None, dev_browser_ui=True), api_token="tool-ui-test")
        uvicorn.run(app, host="127.0.0.1", port=18762, log_level="warning")
