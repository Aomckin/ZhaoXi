import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient

from zhaoxi.core.conversation import Conversation
from zhaoxi.core.agent import AgentResponse
from zhaoxi.permission.models import (
    InvocationOrigin,
    PendingConfirmation,
    PermissionLevel,
    PermissionRequest,
)
from zhaoxi.web.app import create_app
from zhaoxi.web.events import EventBroadcaster


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


def test_web_chat_session_and_clear():
    app = create_app(agent=FakeAgent())
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"message": "你是谁？"})
        assert response.status_code == 200
        assert response.json()["content"] == "你好，暗苟酱。"
        assert len(client.get("/api/session").json()["messages"]) == 2
        assert client.delete("/api/session").json() == {"status": "cleared"}
        assert client.get("/api/session").json()["messages"] == []


def test_permission_card_is_safe_and_approve_resumes_core():
    app = create_app(agent=FakeAgent())
    with TestClient(app) as client:
        waiting = client.post("/api/chat", json={"message": "需要权限"}).json()
        assert waiting["permission"] == {
            "confirmation_id": "confirm-1",
            "action": "写入测试项目",
            "permission": "write",
            "resource_scope": "test:item",
            "risk": "会修改本地状态",
        }
        assert "secret" not in str(waiting)
        completed = client.post("/api/permission/confirm-1/approve")
        assert completed.status_code == 200
        assert completed.json()["content"] == "操作已完成。"


def test_permission_deny_resumes_without_success_claim():
    app = create_app(agent=FakeAgent())
    with TestClient(app) as client:
        client.post("/api/chat", json={"message": "需要权限"})
        denied = client.post("/api/permission/confirm-1/deny")
        assert denied.status_code == 200
        assert denied.json()["content"] == "已拒绝，没有执行。"


def test_core_error_is_sanitized_and_page_remains_available():
    app = create_app(agent=FakeAgent())
    with TestClient(app, raise_server_exceptions=False) as client:
        failed = client.post("/api/chat", json={"message": "boom"})
        assert failed.status_code == 500
        assert "secret traceback" not in failed.text
        assert client.get("/api/health").status_code == 200
        assert "朝汐" in client.get("/").text


async def test_event_broadcaster_delivers_without_polling():
    broadcaster = EventBroadcaster()
    iterator = broadcaster.subscribe()
    pending = asyncio.create_task(anext(iterator))
    await asyncio.sleep(0)
    await broadcaster.publish({"type": "proactive", "content": "提醒"})
    assert await pending == {"type": "proactive", "content": "提醒"}
    await iterator.aclose()
