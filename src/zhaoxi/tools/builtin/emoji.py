"""LLM-facing local emoji expression tool."""

from pydantic import BaseModel, Field

from zhaoxi.expression import EmojiService
from zhaoxi.tools.base import Tool, ToolResult


class SendEmojiInput(BaseModel):
    intent: str = Field(min_length=2, max_length=500)
    emotion: str | None = Field(default=None, max_length=80)
    intensity: float | None = Field(default=None, ge=0, le=1)


class SendEmojiTool(Tool):
    name = "send_emoji"
    description = (
        "在有明显情绪、吐槽、玩笑、邀功、撒娇或尴尬等自然交流场景中，从本地图库选择并发送一张合适表情。"
        "只描述当前想表达的意图，不要猜文件名；无需每次回复都调用。严肃任务、长篇分析与工具执行反馈应降低频率。"
        "no_match 是正常结果，返回后不要立刻换描述反复搜索。"
    )
    input_model = SendEmojiInput
    group = "expression"
    persistent = True

    def __init__(self, service: EmojiService) -> None:
        self.service = service

    @property
    def available(self) -> bool:
        return self.service.enabled and bool(self.service.entries)

    async def execute(self, arguments: SendEmojiInput) -> ToolResult:
        result = self.service.select(arguments.intent, arguments.emotion, arguments.intensity)
        return ToolResult(
            success=True,
            content="已选择合适的本地表情。" if result.status == "matched" else "没有可靠匹配的表情，本次不发送。",
            data=result.model_dump(mode="json"),
        )
