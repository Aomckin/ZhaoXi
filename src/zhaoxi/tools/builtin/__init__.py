from zhaoxi.tools.builtin.calculator import CalculatorTool
from zhaoxi.tools.builtin.current_time import CurrentTimeTool
from zhaoxi.tools.builtin.echo import EchoTool
from zhaoxi.tools.builtin.memory_tools import create_memory_tools
from zhaoxi.memory.service import MemoryService


def create_builtin_tools(memory_service: MemoryService | None = None):
    tools = [EchoTool(), CalculatorTool(), CurrentTimeTool()]
    if memory_service is not None:
        tools.extend(create_memory_tools(memory_service))
    return tools


__all__ = ["CalculatorTool", "CurrentTimeTool", "EchoTool", "create_builtin_tools", "create_memory_tools"]
