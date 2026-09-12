"""Six high-level Tools exposed by the JobApplication Tool Package."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel

from zhaoxi.sdk import PermissionLevel, SideEffect, Tool, ToolResult

from tools.job_application_tool.client import JobApplicationClient
from tools.job_application_tool.errors import JobApplicationError
from tools.job_application_tool.models import (
    ApplySafeFieldsInput,
    BuildPlanInput,
    GetProfileInput,
    GetReviewInput,
    InspectPageInput,
    UpdateProfileInput,
)


class BrowserTool(Tool):
    message_type: ClassVar[str]
    success_content: ClassVar[str]

    def __init__(self, client: JobApplicationClient) -> None:
        self.client = client

    async def execute(self, arguments: BaseModel) -> ToolResult:
        try:
            data = await self.client.call(self.message_type, arguments.model_dump(exclude_none=True))
        except JobApplicationError as exc:
            return ToolResult(
                success=False,
                content=str(exc),
                error=exc.code,
                metadata={"retryable": exc.retryable, "fact_source": "browser_profile"},
            )
        return ToolResult(
            success=True,
            content=self.success_content,
            data=data,
            metadata={"fact_source": "browser_profile", "message_type": self.message_type},
        )

    def resource_scope(self, arguments: dict[str, object]) -> str:
        for key in ("plan_id", "inspection_id", "profile_id", "tab_id"):
            if arguments.get(key) is not None:
                return f"job_application:{key}:{arguments[key]}"
        return f"job_application:{self.message_type}"


class InspectPageTool(BrowserTool):
    name = "job_application_inspect_page"
    description = "只读扫描当前网申页面，识别平台、章节和可填写控件；不读取完整敏感值，不修改页面。"
    input_model = InspectPageInput
    message_type = "inspect_page"
    success_content = "已扫描当前网申页面。"


class BuildPlanTool(BrowserTool):
    name = "job_application_build_plan"
    description = "使用浏览器唯一 Profile、本地中文规则和安全策略生成不可变填写计划；不修改页面。"
    input_model = BuildPlanInput
    message_type = "build_plan"
    success_content = "已在浏览器中生成安全填写计划。"


class ApplySafeFieldsTool(BrowserTool):
    name = "job_application_apply_safe_fields"
    description = "执行浏览器侧不可变计划中的高置信普通字段；永不填写敏感字段、声明、上传或提交控件。"
    input_model = ApplySafeFieldsInput
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.EXTERNAL_SERVICE_WRITE})
    message_type = "apply_safe_fields"
    success_content = "已填写允许自动填写的字段，请在浏览器中检查并手动提交。"

    def safe_to_replay(self, arguments: dict[str, object]) -> bool:
        return False

    def confirmation_description(self, arguments: dict[str, object]) -> str:
        return "在当前网申页面填写计划中的高置信普通字段，不提交申请"


class GetReviewTool(BrowserTool):
    name = "job_application_get_review"
    description = "读取填写结果和待用户处理项，并可在浏览器显示复核面板；不会确认声明或提交申请。"
    input_model = GetReviewInput
    message_type = "get_review"
    success_content = "已读取网申复核结果。"


class GetProfileTool(BrowserTool):
    name = "job_application_get_profile"
    description = "从浏览器唯一 Profile 数据源读取摘要、章节或字段元数据；敏感值只返回掩码状态。"
    input_model = GetProfileInput
    message_type = "get_profile"
    success_content = "已从浏览器 Profile 读取资料。"


class UpdateProfileTool(BrowserTool):
    name = "job_application_update_profile"
    description = "经 revision 校验更新浏览器唯一 Profile 数据源；不会触发页面填写或提交。"
    input_model = UpdateProfileInput
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.LOCAL_STATE})
    message_type = "update_profile"
    success_content = "已更新浏览器 Profile，旧填写计划已失效。"

    def safe_to_replay(self, arguments: dict[str, object]) -> bool:
        return False


def create_tools(client: JobApplicationClient) -> list[Tool]:
    return [
        InspectPageTool(client),
        BuildPlanTool(client),
        ApplySafeFieldsTool(client),
        GetReviewTool(client),
        GetProfileTool(client),
        UpdateProfileTool(client),
    ]
