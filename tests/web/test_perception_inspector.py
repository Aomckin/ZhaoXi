import base64
from types import SimpleNamespace

from fastapi.testclient import TestClient
from web_fixture import FakeAgent

from zhaoxi.config.settings import Settings
from zhaoxi.perception.models import Observation, ObservationPart, ObservationStatus
from zhaoxi.perception.store import PerceptionStore
from zhaoxi.web.app import create_app


def test_recent_perception_api_omits_binary_payload_and_keeps_auth(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = PerceptionStore(tmp_path / "perception.db")
    image = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff" + b"x" * 500_000).decode()
    item = Observation(source="qq", source_kind="group_message", content="图片原文",
                       parts=[ObservationPart(type="image", url=image)])
    store.insert(item, ObservationStatus.PROCESSED)
    monkeypatch.setattr("zhaoxi.perception.PerceptionRuntime", lambda *args: SimpleNamespace(store=store))
    monkeypatch.setattr("zhaoxi.plugins.loader.discover", lambda *args: {})
    settings = Settings(_env_file=None, perception_enabled=True, perception_db_path=str(store.path))
    # No lifespan: the test does not start model or external-source workers.
    client = TestClient(create_app(settings=settings, agent=FakeAgent(), api_token="inspect-test"))
    try:
        assert client.get("/api/perception/recent").status_code == 401
        response = client.get("/api/perception/recent", headers={"X-Zhaoxi-Token": "inspect-test"})
        assert response.status_code == 200
        body = response.json()
        assert body["media_payloads_included"] is False
        assert body["observations"][0]["parts"][0]["url"]["size"] == 500_003
        assert body["observations"][0]["content"] == item.content
        assert body["snapshots"] == []
        assert "data:image/" not in response.text
        assert len(response.content) < 2000
    finally:
        client.close()
