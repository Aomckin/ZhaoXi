from fastapi.testclient import TestClient
from web_fixture import FakeAgent

from zhaoxi.config.settings import Settings
from zhaoxi.web.app import create_app
from zhaoxi.web.events import EventBroadcaster


def publish(bus, request_id, event_type, **extra):
    bus.publish_nowait({"type": "agent_event", "event": {
        "request_id": request_id, "event_type": event_type, **extra,
    }})


def test_snapshot_tracks_latest_request_and_rejects_late_previous_events():
    bus = EventBroadcaster()
    publish(bus, "first", "runtime_started")
    publish(bus, "first", "request_started")
    publish(bus, "second", "runtime_started")
    publish(bus, "first", "tool_call_succeeded")
    publish(bus, "first", "request_started")
    bus.publish_nowait({"type": "maintenance_status", "request_id": "first", "status": "done"})
    publish(bus, "second", "llm_call_started")
    bus.publish_nowait({"type": "maintenance_status", "request_id": "second", "status": "running"})
    result = bus.action_trace_snapshot()
    assert result["request_id"] == "second"
    assert [item["event_type"] for item in result["events"]] == ["runtime_started", "llm_call_started"]
    assert result["maintenance"]["status"] == "running"


def test_snapshot_is_bounded_and_does_not_expose_its_internal_event_list():
    bus = EventBroadcaster()
    publish(bus, "bounded", "runtime_started")
    for index in range(400):
        publish(bus, "bounded", "llm_call_finished", step_id=index)
    result = bus.action_trace_snapshot()
    assert len(result["events"]) == 300
    assert result["events"][0]["event_type"] == "runtime_started"
    assert result["events"][-1]["step_id"] == 399
    result["events"].clear()
    assert len(bus.action_trace_snapshot()["events"]) == 300


def test_runtime_api_returns_completed_and_inflight_trace_with_auth(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None, perception_enabled=False,
                        interface_settings_path=str(tmp_path / "interface.json"))
    app = create_app(agent=FakeAgent(), settings=settings, api_token="trace-test")
    headers = {"X-Zhaoxi-Token": "trace-test"}
    with TestClient(app) as client:
        assert client.get("/api/debug/runtime").status_code == 401
        response = client.post("/api/chat", json={"message": "隔离对话", "request_id": "real-gateway"}, headers=headers)
        assert response.status_code == 200
        saved = client.get("/api/debug/runtime", headers=headers).json()
        assert saved["request_id"] == "real-gateway"
        snapshot = saved["live_action_trace"]
        assert snapshot["request_id"] == "real-gateway"
        assert any(item["event_type"] == "runtime_finished" for item in snapshot["events"])
        assert any(item["event_type"] == "runtime_metrics_finalized" for item in snapshot["events"])
        publish(app.state.events, "inflight", "runtime_started")
        publish(app.state.events, "inflight", "llm_call_started")
        current = client.get("/api/debug/runtime", headers=headers).json()
        assert current["request_id"] == "real-gateway"  # Full metrics still describe the completed request.
        assert current["live_action_trace"]["request_id"] == "inflight"
        assert current["live_action_trace"]["events"][-1]["event_type"] == "llm_call_started"
