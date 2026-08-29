"""Thin interactive command-line interface."""

import asyncio

from zhaoxi.config.logging import configure_logging
from zhaoxi.config.settings import Settings
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.core.conversation import Conversation
from zhaoxi.errors import ZhaoxiError
from zhaoxi.models.openai_compatible import OpenAICompatibleProvider
from zhaoxi.memory.models import MemoryQuery
from zhaoxi.memory.retrieval import MemoryRetriever
from zhaoxi.memory.service import MemoryService
from zhaoxi.memory.sqlite import SQLiteMemoryRepository
from zhaoxi.personality.loader import PersonalityLoader
from zhaoxi.tools.builtin import create_builtin_tools
from zhaoxi.tools.registry import ToolRegistry


def build_agent(settings: Settings) -> ZhaoxiAgent:
    """Wire v0.2 dependencies at the application boundary."""
    settings.validate_model_config()
    provider = OpenAICompatibleProvider(
        base_url=settings.model_base_url,
        api_key=settings.model_api_key,
        model=settings.model_name,
        timeout=settings.request_timeout_seconds,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
    )
    memory_service = MemoryService(SQLiteMemoryRepository(settings.memory_db_path))
    memory_retriever = MemoryRetriever(
        memory_service,
        limit=settings.memory_retrieval_limit,
        max_chars=settings.memory_context_max_chars,
    )
    registry = ToolRegistry()
    for tool in create_builtin_tools(memory_service):
        registry.register(tool)
    return ZhaoxiAgent(
        provider=provider,
        registry=registry,
        context_builder=ContextBuilder(
            PersonalityLoader.load_prompt(), memory_retriever=memory_retriever
        ),
        conversation=Conversation(max_messages=settings.max_context_messages),
        max_steps=settings.max_agent_steps,
        timeout_seconds=settings.request_timeout_seconds,
    )


async def interactive() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    try:
        agent = build_agent(settings)
    except ZhaoxiError as exc:
        print(f"配置错误：{exc}")
        return

    print(
        "Zhaoxi v0.2 · Memory\n"
        "输入 /tools 查看工具，/memory search <关键词> 检索记忆，/clear 清空会话，/exit 退出。"
    )
    while True:
        try:
            text = input("\nYou > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n朝汐 > 再见，暗苟。")
            return
        if not text:
            continue
        if text == "/exit":
            print("朝汐 > 再见，暗苟。")
            return
        if text == "/clear":
            agent.conversation.clear()
            print("朝汐 > 当前会话已清空。")
            continue
        if text == "/tools":
            print("可用工具：" + "、".join(tool.name for tool in agent.registry.list()))
            continue
        if text.startswith("/memory"):
            try:
                await handle_memory_command(agent, text)
            except ZhaoxiError as exc:
                print(f"朝汐 > 记忆操作失败：{exc}")
            continue
        try:
            response = await agent.run(text)
            print(f"朝汐 > {response.content}")
        except ZhaoxiError as exc:
            print(f"朝汐 > 这次没有顺利完成：{exc}")
        except Exception:
            import logging

            logging.getLogger("ERROR").exception("unexpected CLI failure")
            print("朝汐 > 遇到了未预期的内部错误，请查看日志。")


async def handle_memory_command(agent: ZhaoxiAgent, text: str) -> None:
    """Inspect memory without routing maintenance commands through the model."""
    retriever = agent.context_builder.memory_retriever
    if retriever is None:
        print("朝汐 > 长期记忆未启用。")
        return
    parts = text.split(maxsplit=2)
    if len(parts) == 3 and parts[1] == "search":
        results = await retriever.service.search(MemoryQuery(text=parts[2], limit=20))
        if not results:
            print("朝汐 > 没有找到相关记忆。")
            return
        for item in results:
            record = item.record
            print(f"{record.id} [{record.kind.value}] {record.created_at.isoformat()} {record.content}")
        return
    if len(parts) == 3 and parts[1] == "get":
        record = await retriever.service.get(parts[2])
        if record is None:
            print("朝汐 > 没有找到这条记忆。")
        else:
            print(record.model_dump_json(indent=2))
        return
    print("用法：/memory search <关键词> 或 /memory get <memory_id>")


def main() -> None:
    asyncio.run(interactive())
