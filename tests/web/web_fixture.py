"""Shared web agent double; tests should not depend on other test modules."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from zhaoxi.core.agent import AgentResponse
from zhaoxi.core.conversation import Conversation
from zhaoxi.permission.models import (
    InvocationOrigin, PendingConfirmation, PermissionLevel, PermissionRequest,
)


class FakeAgent:
    def __init__(self) -> None:
        self.conversation = Conversation()
        self.pending = {}
        self.tool_executor = SimpleNamespace(
            gateway=SimpleNamespace(store=SimpleNamespace(pending=self.pending))
        )
        self.proactive = None
        self.proactive_scheduler = None
        self.proactive_state = None
        self._pending_permissions = {}
        self.planner = None
        self.workflow = None

    async def run_natural(self, message: str):
        if message == "boom":
            raise RuntimeError("secret traceback")
        if message == "需要权限":
            request = PermissionRequest(
                request_id="request-1",
                tool_name="write_test",
                permission=PermissionLevel.WRITE,
                arguments={"secret": "not-for-ui"},
                arguments_digest="digest",
                resource_scope="test:item",
                action_summary="写入测试项目",
                origin=InvocationOrigin.AGENT,
            )
            pending = PendingConfirmation(
                confirmation_id="confirm-1",
                request=request,
                question="允许吗？",
                risk_summary="会修改本地状态",
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
            self.pending[pending.confirmation_id] = pending
            self._pending_permissions[pending.confirmation_id] = True
            self.conversation.add_user(message)
            self.conversation.add_assistant("需要你的确认。")
            return AgentResponse(
                content="需要你的确认。",
                request_id="request-1",
                steps=1,
                permission_confirmation=pending,
            )
        if message in {"确认", "拒绝"}:
            pending = next(item for item in self.pending.values() if not item.resolved)
            pending.resolved = True
            pending.approved = message == "确认"
            content = "操作已完成。" if pending.approved else "已拒绝，没有执行。"
            self.conversation.add_user(message)
            self.conversation.add_assistant(content)
            return AgentResponse(content=content, request_id="resolved", steps=1)
        self.conversation.add_user(message)
        self.conversation.add_assistant("你好，暗苟酱。")
        return AgentResponse(content="你好，暗苟酱。", request_id="chat-1", steps=1)

    async def approve_permission(self, confirmation_id: str):
        assert confirmation_id in self._pending_permissions
        return await self.run_natural("确认")

    async def deny_permission(self, confirmation_id: str):
        assert confirmation_id in self._pending_permissions
        return await self.run_natural("拒绝")

