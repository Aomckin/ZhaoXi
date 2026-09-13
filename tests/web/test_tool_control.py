from fastapi.testclient import TestClient

from conftest import FakeProvider
from zhaoxi.config.settings import Settings
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.models.types import ModelResponse
from zhaoxi.tools.builtin import create_builtin_tools
from zhaoxi.tools.registry import ToolRegistry
from zhaoxi.web.app import create_app


def build(tmp_path):
    registry = ToolRegistry(tmp_path / "tool_overrides.json")
    for tool in create_builtin_tools():
        registry.register(tool)
    agent = ZhaoxiAgent(provider=FakeProvider([ModelResponse(content="你好")]), registry=registry, context_builder=ContextBuilder("朝汐"))
    app = create_app(agent=agent, settings=Settings(_env_file=None), api_token="test-token")
    return registry, TestClient(app)


def test_manifest_controls_and_authentication(tmp_path):
    registry, client = build(tmp_path)
    assert client.get("/api/debug/tools").status_code == 401
    assert client.post("/api/debug/tools/control", json={"scope": "all", "enabled": False}).status_code == 401
    client.headers["X-Zhaoxi-Token"] = "test-token"
    data = client.get("/api/debug/tools").json()
    assert data["summary"]["registered_tools"] == len(registry.list())
    result = client.post("/api/debug/tools/control", json={"scope": "tool", "target": "calculator", "force_expose": True})
    assert result.status_code == 200
    assert next(t for t in result.json()["tools"] if t["name"] == "calculator")["exposed"]
    result = client.post("/api/debug/tools/control", json={"scope": "group", "target": "calculator", "enabled": False})
    record = next(t for t in result.json()["tools"] if t["name"] == "calculator")
    assert not record["enabled"] and not record["exposed"]
    assert not next(t for t in client.get("/api/capabilities").json()["tools"] if t["name"] == "calculator")["enabled"]
    result = client.post("/api/debug/tools/control", json={"scope": "all", "reset": True})
    record = next(t for t in result.json()["tools"] if t["name"] == "calculator")
    assert record["enabled"] and not record["force_expose"]
    restarted, _ = build(tmp_path)
    assert restarted.control.overrides == {}


def test_controls_reject_unknown_targets_and_invalid_mutations(tmp_path):
    registry, client = build(tmp_path)
    client.headers["X-Zhaoxi-Token"] = "test-token"
    for body in ({"scope": "tool", "target": "missing", "enabled": False}, {"scope": "group", "target": "missing", "enabled": False}):
        assert client.post("/api/debug/tools/control", json=body).status_code == 404
    for body in ({"scope": "tool", "enabled": False}, {"scope": "all"}, {"scope": "all", "enabled": "false"}, {"scope": "all", "reset": True, "enabled": True}):
        assert client.post("/api/debug/tools/control", json=body).status_code == 422
    assert registry.control.overrides == {}
