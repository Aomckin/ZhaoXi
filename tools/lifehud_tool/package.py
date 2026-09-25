"""LifeHUD-Tool package factory and declarative routing hints."""

from pathlib import Path

import httpx

from zhaoxi.sdk import CapabilityDeclaration

from tools.lifehud_tool.autostart import local_lifehud_url
from tools.lifehud_tool.client import LifeHudClient
from tools.lifehud_tool.tool import LifeHudTool


class LifeHudToolPackage:
    package_id = "lifehud-tool"
    package_version = "2.0.0"
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
        def enabled(name: str, default: bool = True) -> bool:
            value = config.get(name, default)
            return value if isinstance(value, bool) else str(value).strip().lower() not in {"0", "false", "no", "off"}
        self.client = LifeHudClient(
            str(config.get("base_url", "http://127.0.0.1:8025")),
            context_path=str(config.get("context_path", "/api/agent/context")),
            schema_version=str(config.get("schema_version", "1")),
            timeout=float(config.get("timeout_seconds", 10)),
            max_retries=int(config.get("max_retries", 2)),
            display_timezone=str(config.get("display_timezone", "Asia/Shanghai")),
            autostart=enabled("autostart_enabled"),
            project_dir=str(config.get("project_dir", Path(__file__).resolve().parents[3] / "Life HUD")),
            startup_timeout_seconds=float(config.get("startup_timeout_seconds", 8)),
            startup_poll_seconds=float(config.get("startup_poll_seconds", 0.4)),
        )

    def create_tools(self, config: dict[str, object]):
        if self.client is None:
            self.configure(config)
        def enabled(name: str) -> bool:
            value = config.get(name + "_enabled", True)
            return value if isinstance(value, bool) else str(value).strip().lower() not in {"0", "false", "no", "off"}
        tool = LifeHudTool(self.client, {name: enabled(name) for name in
                ("context", "write", "image", "focus", "media", "dream", "ritual")})
        tool.default_confirm_write = False
        return [tool]

    def workflow_paths(self) -> list[Path]:
        return [Path(__file__).with_name("workflows")]

    def routing_hints(self) -> list[dict[str, object]]:
        return [
            {"markers": ["朝汐 开幕", "开始铁幕"], "match": "command", "route": "workflow", "workflow_id": "lifehud.iron_curtain.open", "input": "title", "default_input": "铁幕"},
            {"markers": ["朝汐 落幕", "结束铁幕"], "match": "command", "route": "workflow", "workflow_id": "lifehud.iron_curtain.close", "input": "note"},
            {"markers": ["lifehud", "life hud"], "route": "tool"},
            {"markers": ["铁幕开着"], "route": "tool"},
            {"markers": ["记到 LifeHUD", "记进 LifeHUD", "查 LifeHUD", "记录睡眠", "记录饮食", "记录运动", "记录喝水", "记录咖啡", "写日记", "记录番剧", "记录游戏"], "route": "tool"},
        ]

    def capabilities(self) -> dict[str, object]:
        return {
            "id": self.package_id,
            "name": "Life HUD",
            "description": "读取和记录 Life HUD 生活事实；支持图片关联、日记、专注、任务、媒体、仪式和梦想。",
            "tool": "lifehud",
            "read_operations": [
                "context.today", "context.recent", "context.status", "focus.current",
                "context.tasks", "context.dreams", "context.life", "context.journal",
                "context.media", "context.growth",
            ],
            "write_operations": ["record.create", "record.update", "journal.create", "journal.update", "focus.start", "focus.complete", "task.complete", "media.create", "ritual.start", "dream.complete_goal"],
            "examples": ["看看我今天怎么样", "帮我记录昨晚睡眠", "把晚餐照片记进 Life HUD", "朝汐，开幕", "朝汐，落幕"],
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
            response = httpx.get(f"{base_url}{context_path}/status", timeout=0.5,
                                 trust_env=not local_lifehud_url(base_url))
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
