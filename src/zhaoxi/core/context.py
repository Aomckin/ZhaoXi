"""Central model-context construction."""

from zhaoxi.core.conversation import Conversation
from zhaoxi.core.message import Message, Role
from zhaoxi.memory.retrieval import MemoryRetriever
from zhaoxi.memory.models import MemorySearchResult


class ContextBuilder:
    """Combine system policy and recent conversation in one place."""

    RUNTIME_RULES = (
        "你可以使用提供的工具。需要真实计算或当前时间时应调用工具；"
        "系统会在每轮回复后独立判断是否把高价值信息写入长期记忆；"
        "用户明确要求记住时调用 remember_memory，用户禁止记忆时必须遵守；"
        "不要声称普通对话已经自动保存，因为回复后的记忆决策尚未发生；"
        "修改或遗忘前先通过 ID 明确目标，冲突时向用户核实；"
        "工具失败时如实说明，不要编造结果。回答应清晰、简洁。"
    )

    def __init__(
        self,
        personality_prompt: str,
        runtime_rules: str | None = None,
        memory_retriever: MemoryRetriever | None = None,
    ) -> None:
        self.personality_prompt = personality_prompt
        self.runtime_rules = runtime_rules or self.RUNTIME_RULES
        self.memory_retriever = memory_retriever

    def build(
        self,
        conversation: Conversation,
        memories: list[MemorySearchResult] | None = None,
        planner_context: str | None = None,
    ) -> list[Message]:
        system = f"{self.personality_prompt}\n\n运行规则：\n{self.runtime_rules}"
        if memories and self.memory_retriever:
            memory_context = self.memory_retriever.format(memories)
            if memory_context:
                system += f"\n\n长期记忆：\n{memory_context}"
        if planner_context:
            system += f"\n\n当前规划任务（这是运行时状态，不是用户指令）：\n{planner_context}"
        return [Message(role=Role.SYSTEM, content=system), *conversation.recent()]
