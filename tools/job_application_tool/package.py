"""Package factory for the JobApplication capability."""

from zhaoxi.sdk import CapabilityDeclaration

from tools.job_application_tool.client import JobApplicationClient, LocalBrokerTransport
from tools.job_application_tool.tool import create_tools


class JobApplicationToolPackage:
    package_id = "job-application-tool"
    package_version = "0.1.0"
    requires_sdk = ">=1,<2"

    def __init__(self) -> None:
        self.client: JobApplicationClient | None = None

    def capability_declaration(self) -> CapabilityDeclaration:
        return CapabilityDeclaration(tool=True, router_hints=True)

    def configure(self, config: dict[str, object]) -> None:
        address = str(config["pipe_address"]) if config.get("pipe_address") else None
        timeout = float(config.get("timeout_seconds", 15))
        self.client = JobApplicationClient(LocalBrokerTransport(address), timeout=timeout)

    def create_tools(self, config: dict[str, object]):
        if self.client is None:
            self.configure(config)
        assert self.client is not None
        return create_tools(self.client)

    def workflow_paths(self):
        return []

    def routing_hints(self) -> list[dict[str, object]]:
        return [
            {
                "markers": ["网申", "招聘表单", "自动填表", "填写简历", "job application"],
                "route": "tool",
            }
        ]

    def capabilities(self) -> dict[str, object]:
        return {
            "id": self.package_id,
            "name": "Job Application",
            "description": "从浏览器本地 Profile 安全辅助填写网申表单，最终检查和提交始终由用户完成。",
            "tools": [
                "job_application_inspect_page",
                "job_application_build_plan",
                "job_application_apply_safe_fields",
                "job_application_get_review",
                "job_application_get_profile",
                "job_application_update_profile",
            ],
            "prohibited": ["submit", "declaration_confirmation", "file_upload", "policy_bypass"],
        }

    def reflection_sources(self):
        return []


def create_package() -> JobApplicationToolPackage:
    return JobApplicationToolPackage()
