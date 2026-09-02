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
from zhaoxi.reflection.models import (
    EvidenceRef,
    ReflectionKind,
    ReflectionPeriod,
    ReflectionRecord,
    ReflectionStatus,
    SourceSnapshot,
    SourceStatus,
)
from zhaoxi.web.app import create_app
from zhaoxi.web.events import EventBroadcaster
from zhaoxi.interfaces.models import UnifiedResponse
from zhaoxi.voice.models import Transcript, VoiceStatus
from zhaoxi.config.settings import Settings


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


class FakeVoiceRuntime:
    def __init__(self) -> None:
        self.status = VoiceStatus.IDLE
        self.spoken = []
        self.cancelled = False

    async def start_recording(self, device_name=None):
        self.status = VoiceStatus.RECORDING

    async def stop_recording(self):
        self.status = VoiceStatus.REVIEWING
        return Transcript(
            capture_id="capture-1",
            text="语音草稿",
            language="zh-CN",
            provider="fake",
            duration_seconds=1,
        )

    async def confirm_transcript(self, text, *, gateway, request_id=None):
        self.status = VoiceStatus.IDLE
        return UnifiedResponse(
            request_id=request_id or "voice-request",
            trace_id="core-voice",
            content=f"收到：{text}",
        )

    async def cancel(self, reason="user_cancelled"):
        self.cancelled = True
        self.status = VoiceStatus.IDLE

    async def speak(self, text, *, max_chars=1200):
        self.spoken.append((text, max_chars))
        self.status = VoiceStatus.SPEAKING
        return True

    async def stop_speaking(self):
        self.status = VoiceStatus.IDLE


def _reflection_record():
    period = ReflectionPeriod(
        start_at=datetime(2026, 9, 1, tzinfo=UTC),
        end_at=datetime(2026, 9, 2, tzinfo=UTC),
        timezone="Asia/Shanghai",
        label="2026-09-01",
    )
    evidence = EvidenceRef(
        source_type="test",
        source_name="private-source",
        occurred_at=datetime(2026, 9, 1, 12, tzinfo=UTC),
        title="private title",
        excerpt="reflection-private-canary",
        content_hash="12345678",
    )
    return ReflectionRecord(
        reflection_id="reflection-1",
        kind=ReflectionKind.DAILY,
        period=period,
        status=ReflectionStatus.COMPLETED,
        source_snapshots=[SourceSnapshot(
            source="private-source",
            status=SourceStatus.AVAILABLE,
            period=period,
            evidence=[evidence],
        )],
        summary="今日完成核心接线。",
        source_fingerprint="12345678",
    )


class FakeReflectionService:
    def __init__(self):
        self.record = _reflection_record()
        self.repository = SimpleNamespace(list=self.list)

    async def list(self, limit):
        return [self.record]

    async def generate(self, kind, period, *, regenerate=False):
        assert kind is ReflectionKind.DAILY
        return self.record


class FakePeriods:
    def resolve(self, kind):
        return _reflection_record().period


def test_web_chat_session_and_clear():
    app = create_app(agent=FakeAgent())
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"message": "你是谁？"})
        assert response.status_code == 200
        assert response.json()["content"] == "你好，暗苟酱。"
        assert len(client.get("/api/session").json()["messages"]) == 2
        assert client.delete("/api/session").json() == {"status": "cleared"}
        assert client.get("/api/session").json()["messages"] == []


def test_diagnostics_exposes_content_free_metrics():
    app = create_app(agent=FakeAgent())
    with TestClient(app) as client:
        client.post("/api/chat", json={"message": "private canary"})
        payload = client.get("/api/diagnostics").json()

    assert payload["status"] == "ok"
    assert payload["metrics"]["counters"]["interface.chat.completed"] == 1
    assert payload["components"]["voice"] is False
    assert payload["tool_packages"] == []
    assert "private canary" not in str(payload)


def test_web_stays_available_in_first_run_setup_mode(tmp_path):
    settings = Settings(
        model_api_key="",
        model_name="",
        memory_db_path=str(tmp_path / "memory.db"),
    )
    app = create_app(settings=settings)
    with TestClient(app) as client:
        diagnostics = client.get("/api/diagnostics")
        capabilities = client.get("/api/capabilities")
        response = client.post("/api/chat", json={"message": "你好"})

    assert diagnostics.status_code == 200
    assert diagnostics.json()["startup"]["status"] == "needs_configuration"
    assert capabilities.json()["status"] == "setup_required"
    assert "python main.py --doctor" in capabilities.json()["examples"][0]
    assert response.status_code == 200
    assert "ZHAOXI_MODEL_API_KEY" in response.json()["content"]
    assert "Traceback" not in response.text


def test_capabilities_endpoint_is_content_free_for_regular_core():
    app = create_app(agent=FakeAgent())
    with TestClient(app) as client:
        payload = client.get("/api/capabilities").json()
    assert payload == {
        "status": "ready",
        "tools": [],
        "workflows": [],
        "packages": [],
        "examples": [],
    }


def test_reflection_endpoints_return_safe_content_without_raw_evidence():
    agent = FakeAgent()
    agent.reflection = FakeReflectionService()
    agent.reflection_periods = FakePeriods()
    app = create_app(agent=agent)
    with TestClient(app) as client:
        generated = client.post("/api/reflections/daily").json()
        listed = client.get("/api/reflections").json()

    assert generated["summary"] == "今日完成核心接线。"
    assert generated["evidence_count"] == 1
    assert listed["reflections"][0]["reflection_id"] == "reflection-1"
    assert "reflection-private-canary" not in str(generated)
    assert "reflection-private-canary" not in str(listed)


def test_reflection_endpoint_is_unavailable_in_setup_mode():
    app = create_app(agent=FakeAgent())
    with TestClient(app) as client:
        generated = client.post("/api/reflections/daily")
        listed = client.get("/api/reflections")
    assert generated.status_code == 409
    assert listed.status_code == 409


def test_web_request_id_is_idempotent():
    app = create_app(agent=FakeAgent())
    with TestClient(app) as client:
        first = client.post("/api/chat", json={"message": "你好", "request_id": "web-request-1"})
        second = client.post("/api/chat", json={"message": "你好", "request_id": "web-request-1"})
        assert first.json()["request_id"] == "web-request-1"
        assert second.json() == first.json()
        assert len(client.get("/api/session").json()["messages"]) == 2


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


def test_web_shell_has_keyboard_and_live_status_accessibility_baseline():
    app = create_app(agent=FakeAgent())
    with TestClient(app) as client:
        page = client.get("/").text
    assert 'aria-label="发送给朝汐的消息"' in page
    assert 'id="activity" class="activity" role="status" aria-live="polite"' in page
    assert 'id="connection" role="status" aria-live="polite"' in page
    assert "if(e.key==='Enter'&&!e.shiftKey)" in page


def test_desktop_api_token_guards_local_core_routes():
    app = create_app(agent=FakeAgent(), api_token="desktop-secret")
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/session").status_code == 401
        assert anonymous.get("/api/session", headers={"X-Zhaoxi-Token": "wrong"}).status_code == 401
        assert anonymous.post("/api/bootstrap", headers={"X-Zhaoxi-Token": "wrong"}).status_code == 401
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/session").status_code == 401
        bootstrap = client.post(
            "/api/bootstrap", headers={"X-Zhaoxi-Token": "desktop-secret"}
        )
        assert "HttpOnly" in bootstrap.headers["set-cookie"]
        assert "SameSite=strict" in bootstrap.headers["set-cookie"]
        allowed = client.get("/api/session")
        assert allowed.status_code == 200
        assert "desktop-secret" not in allowed.text


async def test_event_broadcaster_delivers_without_polling():
    broadcaster = EventBroadcaster()
    iterator = broadcaster.subscribe()
    pending = asyncio.create_task(anext(iterator))
    await asyncio.sleep(0)
    await broadcaster.publish({"type": "proactive", "content": "提醒"})
    assert await pending == {"type": "proactive", "content": "提醒"}
    await iterator.aclose()


def test_voice_api_exposes_review_confirm_and_stoppable_speech():
    voice = FakeVoiceRuntime()
    app = create_app(agent=FakeAgent(), voice_runtime=voice)
    with TestClient(app) as client:
        assert client.get("/api/voice/status").json() == {"enabled": True, "status": "idle"}
        assert client.post("/api/voice/record/start").json()["status"] == "recording"
        stopped = client.post("/api/voice/record/stop").json()
        assert stopped["status"] == "reviewing"
        assert stopped["text"] == "语音草稿"
        confirmed = client.post(
            "/api/voice/transcript/confirm",
            json={"text": "编辑后的语音", "request_id": "voice-http-1"},
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["content"] == "收到：编辑后的语音"
        assert client.post("/api/voice/speak", json={"text": "朗读我"}).json()["started"]
        assert voice.spoken == [("朗读我", 1200)]
        assert client.post("/api/voice/speak/stop").json() == {"status": "idle"}


def test_explicit_speech_is_deterministic_at_night_with_injected_clock():
    voice = FakeVoiceRuntime()
    settings = Settings(proactive_night_start_hour=23, proactive_night_end_hour=8)
    app = create_app(
        agent=FakeAgent(),
        settings=settings,
        voice_runtime=voice,
        now_provider=lambda: datetime(2026, 9, 1, 23, 30, tzinfo=UTC),
    )
    with TestClient(app) as client:
        response = client.post("/api/voice/speak", json={"text": "夜间显式朗读"}).json()
    assert response["started"] is True
    assert response["reason"] == "explicit_user_action"


def test_voice_api_is_disabled_without_runtime():
    app = create_app(agent=FakeAgent())
    with TestClient(app) as client:
        assert client.get("/api/voice/status").json() == {
            "enabled": False,
            "status": "disabled",
        }
        assert client.post("/api/voice/record/start").status_code == 409
