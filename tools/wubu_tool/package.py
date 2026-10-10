"""Locally discoverable public-SDK package; activation remains Zhaoxi-owned."""
from zhaoxi.sdk import CapabilityDeclaration
from tools.wubu_tool.ledger_tools import create_ledger_tools, OPERATIONS as LEDGER_OPERATIONS
from tools.wubu_tool.client import WubuClient, WubuError
from tools.wubu_tool.tool import CONTRACT, WubuTool
from tools.wubu_tool.high_level import RecordPurchaseTool, ValidatePurchaseTool, InventoryEventTool


class WubuToolPackage:
    package_id = "wubu-tool"
    package_version = "0.2.1"
    requires_sdk = ">=1,<2"

    def __init__(self):
        self.client = None
        self.reachable = self.healthy = None

    def capability_declaration(self):
        return CapabilityDeclaration(tool=True)

    def configure(self, config):
        enabled = config.get("autostart_enabled", True)
        if not isinstance(enabled, bool):
            value = str(enabled).strip().lower()
            if value not in {"1", "true", "yes", "on", "0", "false", "no", "off"}:
                raise ValueError("autostart_enabled 必须是布尔值。")
            enabled = value in {"1", "true", "yes", "on"}
        self.client = WubuClient(str(config.get("base_url", "http://127.0.0.1:8026")),
                                 config.get("timeout_seconds", 15), autostart=enabled,
                                 project_dir=config.get("project_dir"),
                                 startup_timeout=config.get("startup_timeout_seconds", 8))

    def create_tools(self, config):
        if self.client is None:
            self.configure(config)
        return [RecordPurchaseTool(self.client), ValidatePurchaseTool(self.client),
                InventoryEventTool(self.client), WubuTool(self.client)] + create_ledger_tools(self.client)

    def capabilities(self):
        return {"id": self.package_id, "name": "物簿", "tool": "record_purchase",
                "tools": ["record_purchase", "validate_purchase", "wubu_inventory_event", "wubu", *LEDGER_OPERATIONS],
                "description": "购买、库存、耐用品、维护和费用的本地 REST 接口。",
                "read_operations": [k for k, v in CONTRACT.items() if v["method"] == "GET" or k == "validate_purchase"],
                "write_operations": [k for k, v in CONTRACT.items() if v["method"] != "GET" and k != "validate_purchase"]}

    def workflow_paths(self):
        return []

    def routing_hints(self):
        return []

    def reflection_sources(self):
        return []

    def health_check(self, config):
        try:
            client = WubuClient(str(config.get("base_url", "http://127.0.0.1:8026")), 0.5)
            data, _ = client.request("GET", "/healthz")
            self.reachable = True
            self.healthy = isinstance(data, dict) and data.get("status") == "ok" and data.get("database") == "ok"
        except (WubuError, ValueError):
            self.reachable = self.healthy = False
        return {"configured": True, **self.status()}

    def status(self):
        return {"reachable": self.reachable, "healthy": self.healthy, "backoff_until": None}


def create_package():
    return WubuToolPackage()
