from fastapi.testclient import TestClient
from pydantic import BaseModel

from conftest import FakeProvider
from zhaoxi.config.settings import Settings
from zhaoxi.core.agent import ZhaoxiAgent
from zhaoxi.core.context import ContextBuilder
from zhaoxi.models.types import ModelResponse
from zhaoxi.tools.builtin import create_builtin_tools
from zhaoxi.tools.registry import ToolRegistry
from zhaoxi.tools.base import Tool, ToolResult
from zhaoxi.permission.models import PermissionLevel, SideEffect
from zhaoxi.web.app import create_app
from tools.lifehud_tool import LifeHudClient, LifeHudTool


class WriteInput(BaseModel):
    path: str


class WriteFixtureTool(Tool):
    name = "write_fixture"
    description = "测试写钥匙。"
    input_model = WriteInput
    permission = PermissionLevel.WRITE
    side_effects = frozenset({SideEffect.LOCAL_STATE})

    async def execute(self, arguments):
        return ToolResult(success=True, content="ok")


def build(tmp_path):
    registry = ToolRegistry(tmp_path / "tool_overrides.json")
    for tool in create_builtin_tools():
        registry.register(tool)
    registry.register(WriteFixtureTool())
    registry.register(LifeHudTool(LifeHudClient("http://lifehud.test")))
    agent = ZhaoxiAgent(provider=FakeProvider([ModelResponse(content="你好")]), registry=registry, context_builder=ContextBuilder("朝汐"))
    app = create_app(
        agent=agent,
        settings=Settings(
            _env_file=None,
            filesystem_access_path=str(tmp_path / "filesystem-access.json"),
        ),
        api_token="test-token",
    )
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
    result = client.post("/api/debug/tools/control", json={
        "scope": "tool", "target": "write_fixture", "confirm_write": False,
    })
    memory = next(t for t in result.json()["tools"] if t["name"] == "write_fixture")
    assert memory["write_capable"] and memory["confirm_write"] is False
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
    for body in ({"scope": "tool", "enabled": False}, {"scope": "all"}, {"scope": "all", "enabled": "false"}, {"scope": "all", "confirm_write": "false"}, {"scope": "all", "reset": True, "enabled": True}):
        assert client.post("/api/debug/tools/control", json=body).status_code == 422
    assert registry.control.overrides == {}


def test_lifehud_capability_switches_apply_live_and_persist(tmp_path):
    registry, client = build(tmp_path)
    assert client.post("/api/debug/tools/capability", json={
        "tool": "lifehud", "capability": "image", "enabled": False,
    }).status_code == 401
    client.headers["X-Zhaoxi-Token"] = "test-token"
    response = client.post("/api/debug/tools/capability", json={
        "tool": "lifehud", "capability": "image", "enabled": False,
    })
    assert response.status_code == 200
    lifehud = next(tool for tool in response.json()["tools"] if tool["name"] == "lifehud")
    assert lifehud["capabilities"]["image"] is False
    assert registry.get("lifehud").capability_flags()["image"] is False
    restarted, _ = build(tmp_path)
    assert restarted.get("lifehud").capability_flags()["image"] is False
    for body in ({"tool": "lifehud", "capability": "missing", "enabled": True},
                 {"tool": "calculator", "capability": "image", "enabled": True}):
        assert client.post("/api/debug/tools/capability", json=body).status_code == 404
    assert client.post("/api/debug/tools/capability", json={
        "tool": "lifehud", "capability": "image", "enabled": "false",
    }).status_code == 422
    reset = client.post("/api/debug/tools/control", json={
        "scope": "tool", "target": "lifehud", "reset": True,
    })
    assert reset.status_code == 200
    assert registry.get("lifehud").capability_flags()["image"] is True


def test_filesystem_access_paths_are_validated_and_persisted(tmp_path):
    _, client = build(tmp_path)
    client.headers["X-Zhaoxi-Token"] = "test-token"
    first = tmp_path / "资料"
    second = tmp_path / "项目"
    writable = second / "朝汐输出"
    first.mkdir()
    second.mkdir()
    writable.mkdir()

    response = client.put("/api/tools/filesystem-access", json={
        "read_directories": [str(first), str(second), str(first)],
        "write_directories": [str(writable)],
    })

    assert response.status_code == 200
    assert response.json() == {
        "read_directories": [str(first.resolve()), str(second.resolve())],
        "write_directories": [str(writable.resolve())],
        "restart_required": True,
        "message": "已保存，重启 Core 后生效。",
    }
    snapshot = client.get("/api/debug/tools").json()
    assert snapshot["filesystem_access"]["read_directories"] == response.json()["read_directories"]
    assert snapshot["filesystem_access"]["write_directories"] == response.json()["write_directories"]
    assert client.put("/api/tools/filesystem-access", json={
        "read_directories": ["relative/path"],
        "write_directories": [str(writable)],
    }).status_code == 422
    assert client.put("/api/tools/filesystem-access", json={
        "read_directories": [str(first)],
        "write_directories": [str(tmp_path / "不存在")],
    }).status_code == 422
    assert client.put("/api/tools/filesystem-access", json={
        "read_directories": [str(first)],
        "write_directories": [str(second)],
    }).status_code == 422
