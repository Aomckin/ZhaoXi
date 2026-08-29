from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field

from zhaoxi.tools.base import Tool, ToolResult


class CurrentTimeInput(BaseModel):
    timezone: str | None = Field(default=None, description="可选 IANA 时区，如 Asia/Shanghai；留空使用系统时区")


class CurrentTimeTool(Tool):
    name = "current_time"
    description = "获取当前日期、时间和时区。"
    input_model = CurrentTimeInput

    async def execute(self, arguments: CurrentTimeInput) -> ToolResult:
        try:
            now = datetime.now(ZoneInfo(arguments.timezone)) if arguments.timezone else datetime.now().astimezone()
        except ZoneInfoNotFoundError as exc:
            return ToolResult(success=False, content="无法识别该时区。", error=str(exc))
        timezone_name = getattr(now.tzinfo, "key", None) or str(now.tzinfo)
        data = {
            "iso_datetime": now.isoformat(),
            "timezone": timezone_name,
            "human_readable": now.strftime("%Y年%m月%d日 %H:%M:%S"),
        }
        return ToolResult(success=True, content=data["human_readable"], data=data)
