"""Read-only tools for the Life HUD v0.8 Agent Context API."""

from collections.abc import Awaitable, Callable
from typing import Any

from zhaoxi.tools.base import Tool, ToolResult
from zhaoxi.tools.integrations.lifehud.client import LifeHudClient
from zhaoxi.tools.integrations.lifehud.errors import LifeHudError
from zhaoxi.tools.integrations.lifehud.models import EmptyInput, JournalInput, RecentInput


class LifeHudContextTool(Tool):
    def __init__(self, client: LifeHudClient) -> None:
        self.client = client

    def error(self, exc: LifeHudError) -> ToolResult:
        return ToolResult(
            success=False,
            content=str(exc),
            error=exc.code,
            metadata={"retryable": exc.retryable, "fact_source": "lifehud"},
        )

    async def read(self, operation: Callable[[], Awaitable[Any]]) -> ToolResult:
        try:
            value = await operation()
        except LifeHudError as exc:
            return self.error(exc)
        return ToolResult(
            success=True,
            content="已从 Life HUD 读取事实。",
            data=self.client.dump_for_display(value),
            metadata={
                "fact_source": "lifehud",
                "requeryable": True,
                "display_timezone": self.client.display_timezone,
            },
        )


class LifeHudTodayTool(LifeHudContextTool):
    name = "lifehud_today"
    description = "读取 Life HUD 今日整体上下文；适合回答今天怎么样、今天做了什么、接下来做什么和当前整体状态。"
    input_model = EmptyInput

    async def execute(self, arguments):
        return await self.read(self.client.today)


class LifeHudRecentTool(LifeHudContextTool):
    name = "lifehud_recent"
    description = "读取 Life HUD 最近 1 到 30 个自然日的摘要和时间线；适合一周回顾、近期趋势和最近发生了什么。"
    input_model = RecentInput

    async def execute(self, arguments):
        return await self.read(lambda: self.client.recent(arguments.days))


class LifeHudStatusTool(LifeHudContextTool):
    name = "lifehud_status"
    description = "读取 Life HUD 当前 Energy、等级、称号、最近 Check-in 和活动 Focus。"
    input_model = EmptyInput

    async def execute(self, arguments):
        return await self.read(self.client.status)


class LifeHudFocusTool(LifeHudContextTool):
    name = "lifehud_focus"
    description = "读取 Life HUD 今日专注统计、当前 Focus、近期 Session 和七日趋势；适合查询今天专注多久或当前是否在铁幕。"
    input_model = EmptyInput

    async def execute(self, arguments):
        return await self.read(self.client.focus)


class LifeHudTasksTool(LifeHudContextTool):
    name = "lifehud_tasks"
    description = "读取 Life HUD 当前每日任务与特别行动；适合查询已完成、剩余任务和方向关联。"
    input_model = EmptyInput

    async def execute(self, arguments):
        return await self.read(self.client.tasks)


class LifeHudDreamsTool(LifeHudContextTool):
    name = "lifehud_dreams"
    description = "读取 Life HUD 活跃 Dream、活跃 Goal 与 Milestone。"
    input_model = EmptyInput

    async def execute(self, arguments):
        return await self.read(self.client.dreams)


class LifeHudLifeTool(LifeHudContextTool):
    name = "lifehud_life"
    description = "读取 Life HUD 今日睡眠、饮食、生活记录及最近运动和 Check-in；空值表示尚无记录，不表示异常。"
    input_model = EmptyInput

    async def execute(self, arguments):
        return await self.read(self.client.life)


class LifeHudJournalTool(LifeHudContextTool):
    name = "lifehud_journal"
    description = "读取 Life HUD 最近日记和近期时间线；适合查询最近写了什么。"
    input_model = JournalInput

    async def execute(self, arguments):
        return await self.read(lambda: self.client.journal(arguments.limit))


class LifeHudMediaTool(LifeHudContextTool):
    name = "lifehud_media"
    description = "读取 Life HUD 在看、在玩、进行中的作品与近期观看或游玩 Session。"
    input_model = EmptyInput

    async def execute(self, arguments):
        return await self.read(self.client.media)


class LifeHudGrowthTool(LifeHudContextTool):
    name = "lifehud_growth"
    description = "读取 Life HUD 当前成长状态、近期结算记录与七日快照。"
    input_model = EmptyInput

    async def execute(self, arguments):
        return await self.read(self.client.growth)


def create_lifehud_context_tools(client: LifeHudClient):
    return [
        LifeHudTodayTool(client),
        LifeHudRecentTool(client),
        LifeHudStatusTool(client),
        LifeHudFocusTool(client),
        LifeHudTasksTool(client),
        LifeHudDreamsTool(client),
        LifeHudLifeTool(client),
        LifeHudJournalTool(client),
        LifeHudMediaTool(client),
        LifeHudGrowthTool(client),
    ]
