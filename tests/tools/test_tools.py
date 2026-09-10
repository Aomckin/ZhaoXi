import pytest

from zhaoxi.errors import ToolNotFoundError, ToolValidationError
from zhaoxi.tools.builtin.calculator import CalculatorTool
from zhaoxi.tools.builtin.current_time import CurrentTimeTool
from zhaoxi.tools.builtin.echo import EchoTool
from zhaoxi.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_echo_and_schema():
    tool = EchoTool()
    result = await tool.run({"message": "汪"})
    assert result.success and result.content == "汪"
    assert tool.schema()["function"]["parameters"]["required"] == ["message"]


@pytest.mark.asyncio
async def test_calculator_accepts_only_safe_arithmetic():
    tool = CalculatorTool()
    assert (await tool.run({"expression": "17 * 23"})).data["result"] == 391
    assert (await tool.run({"expression": "2 ** 8 + (9 % 4)"})).data["result"] == 257
    invalid = await tool.run({"expression": "__import__('os').getcwd()"})
    assert not invalid.success
    assert (await tool.run({"expression": "1 / 0"})).success is False


@pytest.mark.asyncio
async def test_current_time_and_invalid_timezone():
    result = await CurrentTimeTool().run({})
    assert result.success
    assert {"iso_datetime", "timezone", "human_readable"} <= result.data.keys()
    assert not (await CurrentTimeTool().run({"timezone": "Not/A_Zone"})).success


def test_registry_lifecycle_and_duplicate():
    registry = ToolRegistry()
    tool = registry.register(EchoTool())
    assert registry.get("echo") is tool
    assert len(registry.schemas()) == 1
    with pytest.raises(ToolValidationError):
        registry.register(EchoTool())
    assert registry.unregister("echo") is tool
    with pytest.raises(ToolNotFoundError):
        registry.get("echo")


def test_registry_dynamically_registers_refreshes_and_closes_tool_provider():
    class Provider:
        provider_id = "dynamic-test"

        def __init__(self):
            self.tools = [EchoTool()]
            self.closed = False

        def provide_tools(self):
            return self.tools

        def close(self):
            self.closed = True

    provider = Provider()
    registry = ToolRegistry()
    assert [tool.name for tool in registry.register_provider(provider)] == ["echo"]
    assert registry.get("echo") is provider.tools[0]

    provider.tools = [CurrentTimeTool()]
    assert [tool.name for tool in registry.refresh_provider(provider.provider_id)] == ["current_time"]
    with pytest.raises(ToolNotFoundError):
        registry.get("echo")

    assert registry.close_providers() == []
    assert provider.closed
