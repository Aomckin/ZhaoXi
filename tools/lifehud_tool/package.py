"""LifeHUD-Tool package factory and declarative routing hints."""

from pathlib import Path

from tools.lifehud_tool.client import LifeHudClient
from tools.lifehud_tool.tool import LifeHudTool


class LifeHudToolPackage:
    package_id = "lifehud-tool"
    package_version = "1.0.0"

    def __init__(self) -> None:
        self.client = None

    def create_tools(self, config: dict[str, object]):
        client = LifeHudClient(
            str(config.get("base_url", "http://127.0.0.1:8025")),
            context_path=str(config.get("context_path", "/api/agent/context")),
            schema_version=str(config.get("schema_version", "1")),
            timeout=float(config.get("timeout_seconds", 10)),
            max_retries=int(config.get("max_retries", 2)),
            display_timezone=str(config.get("display_timezone", "Asia/Shanghai")),
        )
        self.client = client
        return [LifeHudTool(client)]

    def workflow_paths(self) -> list[Path]:
        return [Path(__file__).with_name("workflows")]

    def routing_hints(self) -> list[dict[str, object]]:
        return [
            {"markers": ["开幕", "开始铁幕"], "route": "workflow", "workflow_id": "lifehud.iron_curtain.open", "input": "title", "default_input": "铁幕"},
            {"markers": ["落幕", "结束铁幕"], "route": "workflow", "workflow_id": "lifehud.iron_curtain.close", "input": "note"},
            {"markers": ["lifehud", "life hud"], "route": "tool"},
            {"markers": ["铁幕开着"], "route": "tool"},
        ]

    def capabilities(self) -> dict[str, object]:
        return {
            "id": self.package_id,
            "name": "Life HUD",
            "description": "读取生活事实，并在明确确认后开启或结束铁幕 Focus。",
            "tool": "lifehud",
            "read_operations": [
                "context.today", "context.recent", "context.status", "focus.current",
                "context.tasks", "context.dreams", "context.life", "context.journal",
                "context.media", "context.growth",
            ],
            "write_operations": ["focus.start", "focus.complete"],
            "examples": ["看看我今天怎么样", "朝汐，开幕，完成当前任务", "朝汐，落幕"],
        }

    def reflection_sources(self):
        if self.client is None:
            return []
        from tools.lifehud_tool.reflection import LifeHudReflectionSource

        return [LifeHudReflectionSource(self.client)]

    def capabilities(self) -> dict[str, object]:
        return {
            "id": self.package_id,
            "name": "Life HUD",
            "description": "读取生活事实，并在明确确认后开启或结束铁幕 Focus。",
            "tool": "lifehud",
            "read_operations": [
                "context.today", "context.recent", "context.status", "focus.current",
                "context.tasks", "context.dreams", "context.life", "context.journal",
                "context.media", "context.growth",
            ],
            "write_operations": ["focus.start", "focus.complete"],
            "examples": ["看看我今天怎么样", "朝汐，开幕，完成当前任务", "朝汐，落幕"],
        }


def create_package() -> LifeHudToolPackage:
    return LifeHudToolPackage()
