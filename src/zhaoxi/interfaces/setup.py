"""Safe local Core substitute used only when startup prerequisites are missing."""

from types import SimpleNamespace

from zhaoxi.core.agent import AgentResponse
from zhaoxi.core.conversation import Conversation
from zhaoxi.reliability.metrics import MetricRegistry


class StartupUnavailableAgent:
    """Keep local interfaces open while preventing normal Agent execution."""

    def __init__(self, diagnostics: dict[str, object], reason: str) -> None:
        self.startup_diagnostics = diagnostics
        self.startup_error = reason
        self.conversation = Conversation()
        self.metrics = MetricRegistry()
        self.provider = None
        self.planner = None
        self.workflow = None
        self.reflection = None
        self.reflection_periods = None
        self.proactive = None
        self.proactive_scheduler = None
        self.proactive_state = None
        self.backup_manager = None
        self.tool_packages = diagnostics.get("tool_packages", [])
        self.capability_catalog = {
            "status": "setup_required",
            "tools": [],
            "workflows": [],
            "packages": [],
            "examples": ["先运行 python main.py --doctor 完成首次配置。"],
        }
        self.capability_catalog = {
            "status": "setup_required",
            "tools": [],
            "workflows": [],
            "packages": [],
            "examples": ["先运行 python main.py --doctor 完成首次配置。"],
        }
        self._pending_permissions = {}
        self.tool_executor = SimpleNamespace(
            gateway=SimpleNamespace(store=SimpleNamespace(pending={}))
        )

    async def run_natural(self, message: str, *, images: list[str] | None = None) -> AgentResponse:
        model = self.startup_diagnostics["checks"]["model"]
        action = model.get("action") or "运行 python main.py --doctor 查看启动诊断。"
        content = f"朝汐尚未完成启动配置。{action}"
        return AgentResponse(content=content, request_id="startup-unavailable", steps=0)
