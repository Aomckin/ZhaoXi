from types import SimpleNamespace

from fastapi.testclient import TestClient
from test_web import FakeAgent

from zhaoxi.config.settings import Settings
from zhaoxi.web.app import create_app
from zhaoxi.web.events import EventBroadcaster


def test_quick_debug_partial_updates_preserve_timings_and_broadcast(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None, perception_enabled=False,
                        interface_settings_path=str(tmp_path / "interface.json"))
    agent = FakeAgent()
    agent.timeout_seconds = 45
    agent.cognitive = SimpleNamespace(force_fast_chat=False)
    emitted = []
    original = EventBroadcaster.publish

    async def publish(self, event):
        emitted.append(event)
        await original(self, event)

    monkeypatch.setattr(EventBroadcaster, "publish", publish)
    app = create_app(agent=agent, settings=settings, api_token="quick-debug")
    headers = {"X-Zhaoxi-Token": "quick-debug"}
    with TestClient(app) as client:
        assert client.patch("/api/settings/interface", json={"force_fast_chat": True}).status_code == 401
        saved = client.put("/api/settings/interface", headers=headers, json={
            "input_merge_seconds": 7, "reply_interval_seconds": 2,
            "external_input_debounce_seconds": 3, "external_reply_interval_seconds": 1.2,
        }).json()
        for key in ("long_wait_enabled", "force_fast_chat", "show_normal_regenerate"):
            response = client.patch("/api/settings/interface", headers=headers, json={key: True})
            assert response.status_code == 200
            saved[key] = True
            assert response.json() == saved
        assert agent.timeout_seconds == 120
        assert agent.cognitive.force_fast_chat is True
        assert emitted[-1] == {"type": "interface_settings", "settings": saved}
        assert client.get("/api/settings/interface", headers=headers).json() == saved
    with TestClient(create_app(agent=FakeAgent(), settings=settings, api_token="quick-debug")) as client:
        assert client.get("/api/settings/interface", headers=headers).json() == saved


def test_invalid_quick_debug_patch_keeps_saved_settings(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None, perception_enabled=False,
                        interface_settings_path=str(tmp_path / "interface.json"))
    with TestClient(create_app(agent=FakeAgent(), settings=settings)) as client:
        saved = client.patch("/api/settings/interface", json={"input_merge_seconds": 7}).json()
        for patch in ({"show_normal_regenerate": "true"}, {"long_wait_enabled": None},
                      {"force_fast_chat": 1}, {"reply_interval_seconds": 99}):
            assert client.patch("/api/settings/interface", json=patch).status_code == 422
            assert client.get("/api/settings/interface").json() == saved
