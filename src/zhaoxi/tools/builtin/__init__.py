from zhaoxi.tools.builtin.calculator import CalculatorTool
from zhaoxi.tools.builtin.current_time import CurrentTimeTool
from zhaoxi.tools.builtin.echo import EchoTool
from zhaoxi.tools.builtin.memory_tools import create_memory_tools
from zhaoxi.tools.builtin.archive_tools import create_archive_tools
from zhaoxi.archive.service import ArchiveService
from zhaoxi.memory.service import MemoryService
from zhaoxi.expression import EmojiService
from zhaoxi.tools.builtin.emoji import SendEmojiTool


def create_builtin_tools(
    memory_service: MemoryService | None = None,
    archive_service: ArchiveService | None = None,
    emoji_service: EmojiService | None = None,
):
    tools = [EchoTool(), CalculatorTool(), CurrentTimeTool()]
    if memory_service is not None:
        tools.extend(create_memory_tools(memory_service))
    if archive_service is not None:
        tools.extend(create_archive_tools(archive_service))
    if emoji_service is not None:
        tools.append(SendEmojiTool(emoji_service))
    return tools


__all__ = [
    "CalculatorTool", "CurrentTimeTool", "EchoTool", "create_builtin_tools",
    "create_memory_tools", "create_archive_tools", "SendEmojiTool",
]
