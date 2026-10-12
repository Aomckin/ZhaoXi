from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from web_fixture import FakeAgent

from zhaoxi.config.settings import Settings
from zhaoxi.decision.awareness import DecisionAwareness
from zhaoxi.decision.history import ChoiceHistory
from zhaoxi.decision.models import DecisionAwarenessTrace
from zhaoxi.web.app import create_app


def test_debug_is_authenticated_read_only_and_agency_never_runs_classifier(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    core = FakeAgent()
    core.decision_mode = "agency"
    core.last_reply_protocol = {"status":"failed", "error_code":"empty_model_reply", "input_chars":3}
    core.decision_awareness = DecisionAwareness(history=ChoiceHistory(tmp_path / "choices"))
    core.decision_service = SimpleNamespace(evaluate=AsyncMock(side_effect=AssertionError("classifier")))
    trace = DecisionAwarenessTrace(mode="ADVISE", decision_kind="NEW",
                                   decision_question="如何平衡下午的娱乐与项目进度", agent_recommendation="去打舞萌",
                                   predicted_user_choice="继续项目")
    core.decision_awareness.recent_traces.append(trace.model_dump(mode="json"))
    core.decision_awareness.history.record("test", trace, "下午安排", scope="owner:desktop:local")
    core.decision_awareness.history.feedback("test", "继续项目", scope="owner:desktop:local", overridden=True)
    core.tool_executor.recent_decision_guard_events = [{"tool":"payment","flags":["external_action"],"status":"require_confirmation"}]
    client = TestClient(create_app(settings=Settings(_env_file=None, perception_enabled=False),
                                  agent=core, api_token="test"))
    headers = {"X-Zhaoxi-Token":"test"}
    try:
        assert client.get("/api/debug/decision").status_code == 401
        body = client.get("/api/debug/decision", headers=headers).json()
        assert body["decision_mode"] == "agency" and body["latest"]["mode"] == "ADVISE"
        assert body["choice_history"][0]["overridden"]
        assert body["guard_events"][0]["status"] == "require_confirmation"
        assert body["reply_protocol"]["error_code"] == "empty_model_reply"
        response = client.post("/api/debug/decision", headers=headers, json={"message":"吃啥？"})
        assert response.status_code == 409
        core.decision_service.evaluate.assert_not_awaited()
    finally:
        client.close()


def test_legacy_debug_remains_available(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    core = FakeAgent()
    core.decision_mode = "legacy"
    core.decision_service = SimpleNamespace(diagnostics=lambda: {"triggered":False,"result":None})
    client = TestClient(create_app(settings=Settings(_env_file=None, perception_enabled=False), agent=core))
    try:
        body = client.get("/api/debug/decision").json()
        assert body["decision_mode"] == "legacy" and body["result"] is None
    finally:
        client.close()
