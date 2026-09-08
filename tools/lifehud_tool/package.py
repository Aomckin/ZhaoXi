"""LifeHUD-Tool package factory and declarative routing hints."""

from pathlib import Path

import httpx

from zhaoxi.sdk import CapabilityDeclaration

from tools.lifehud_tool.client import LifeHudClient
from tools.lifehud_tool.tool import LifeHudTool


class LifeHudToolPackage:
    package_id = "lifehud-tool"
    package_version = "1.1.0"
    requires_sdk = ">=1,<2"

    def __init__(self) -> None:
        self.client = None
        self.provider = None
        self.reachable = None
        self.healthy = None
        self.backoff_until = None

    def capability_declaration(self) -> CapabilityDeclaration:
        return CapabilityDeclaration(
            tool=True,
            workflow=True,
            router_hints=True,
            proactive_provider=True,
            reflection_provider=True,
            state_signal_provider=True,
        )

    def configure(self, config: dict[str, object]) -> None:
        self.client = LifeHudClient(
            str(config.get("base_url", "http://127.0.0.1:8025")),
            context_path=str(config.get("context_path", "/api/agent/context")),
            schema_version=str(config.get("schema_version", "1")),
            timeout=float(config.get("timeout_seconds", 10)),
            max_retries=int(config.get("max_retries", 2)),
            display_timezone=str(config.get("display_timezone", "Asia/Shanghai")),
        )

    def create_tools(self, config: dict[str, object]):
        if self.client is None:
            self.configure(config)
        return [LifeHudTool(self.client)]

    def workflow_paths(self) -> list[Path]:
        return [Path(__file__).with_name("workflows")]

    def routing_hints(self) -> list[dict[str, object]]:
        return [
            {"markers": ["朝汐 开幕", "开始铁幕"], "match": "command", "route": "workflow", "workflow_id": "lifehud.iron_curtain.open", "input": "title", "default_input": "铁幕"},
            {"markers": ["朝汐 落幕", "结束铁幕"], "match": "command", "route": "workflow", "workflow_id": "lifehud.iron_curtain.close", "input": "note"},
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

    def proactive_sensors(self):
        if self.client is None:
            return []
        from tools.lifehud_tool.proactive import LifeHudSensor
        if self.provider is None:
            self.provider = LifeHudSensor(self.client, status_owner=self)
        return [self.provider]

    def state_signal_providers(self):
        return self.proactive_sensors()

    def reflection_sources(self):
        if self.client is None:
            return []
        from tools.lifehud_tool.reflection import LifeHudReflectionSource

        return [LifeHudReflectionSource(self.client)]

    def health_check(self, config: dict[str, object]) -> dict[str, object]:
        base_url = str(config.get("base_url", "http://127.0.0.1:8025")).rstrip("/")
        context_path = "/" + str(config.get("context_path", "/api/agent/context")).strip("/")
        configured = bool(base_url)
        try:
            response = httpx.get(f"{base_url}{context_path}/status", timeout=0.5)
            response.raise_for_status()
            payload = response.json()
            healthy = payload.get("schemaVersion") == str(config.get("schema_version", "1"))
            self.reachable = True
            self.healthy = healthy
        except Exception:
            self.reachable = False
            self.healthy = False
        return {
            "configured": configured,
            "reachable": self.reachable,
            "healthy": self.healthy,
        }

    def status(self) -> dict[str, object]:
        if self.provider is not None:
            self.reachable = self.provider.reachable
            self.healthy = self.provider.healthy
            self.backoff_until = self.provider.next_poll if self.provider.failures else None
        return {
            "reachable": self.reachable,
            "healthy": self.healthy,
            "backoff_until": self.backoff_until,
        }


def create_package() -> LifeHudToolPackage:
    return LifeHudToolPackage()
