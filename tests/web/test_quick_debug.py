from types import SimpleNamespace

from fastapi.testclient import TestClient
from web_fixture import FakeAgent

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
                      {"allow_multi_model_calls": "true"}, {"force_non_fast_chat": 1},
                      {"force_fast_chat": True, "force_non_fast_chat": True},
                      {"force_fast_chat": 1}, {"reply_interval_seconds": 99}):
            assert client.patch("/api/settings/interface", json=patch).status_code == 422
            assert client.get("/api/settings/interface").json() == saved


def test_runtime_debug_switches_are_exclusive_live_and_restored(tmp_path):
    settings = Settings(perception_enabled=False, interface_settings_path=str(tmp_path / "interface.json"))
    agent = FakeAgent()
    agent.cognitive = SimpleNamespace(force_fast_chat=False, force_non_fast_chat=False)
    with TestClient(create_app(agent=agent, settings=settings)) as client:
        baseline = client.patch("/api/settings/interface", json={"input_merge_seconds": 7, "force_fast_chat": True}).json()
        saved = client.patch("/api/settings/interface", json={"force_non_fast_chat": True, "allow_multi_model_calls": True}).json()
        assert saved["input_merge_seconds"] == baseline["input_merge_seconds"] == 7
        assert saved["force_non_fast_chat"] is True and saved["force_fast_chat"] is False
        assert agent.cognitive.force_non_fast_chat is True and agent.cognitive.force_fast_chat is False
        assert agent.allow_multi_model_calls is True
        assert client.put("/api/settings/interface", json={"force_fast_chat": True, "force_non_fast_chat": True}).status_code == 422
        assert client.get("/api/settings/interface").json() == saved
    restored = FakeAgent()
    restored.cognitive = SimpleNamespace(force_fast_chat=False, force_non_fast_chat=False)
    with TestClient(create_app(agent=restored, settings=settings)) as client:
        assert restored.cognitive.force_non_fast_chat is True and restored.allow_multi_model_calls is True
        switched = client.patch("/api/settings/interface", json={"force_fast_chat": True}).json()
        assert switched["force_non_fast_chat"] is False and switched["force_fast_chat"] is True
        assert switched["allow_multi_model_calls"] is True
        assert restored.cognitive.force_non_fast_chat is False
        assert client.patch("/api/settings/interface", json={"allow_multi_model_calls": False}).status_code == 200
        assert restored.allow_multi_model_calls is False


def test_budget_controls_apply_to_gateway_restore_and_reset(tmp_path):
    from zhaoxi.reliability.retry import current_budget, BudgetExtensionRequest
    settings = Settings(_env_file=None, perception_enabled=False,
                        interface_settings_path=str(tmp_path / "interface.json"),
                        request_max_total_tokens=40_000, request_hard_limit_tokens=70_000,
                        request_extension_1_limit_tokens=8_000, request_finalization_reserve_tokens=3_000)
    agent = FakeAgent()
    agent.provider = SimpleNamespace(max_calls=12, max_total_tokens=100_000)
    seen = []
    original = agent.run_natural

    async def run(message):
        budget = current_budget()
        budget.total_tokens = 16_000
        decision = budget.request_extension(BudgetExtensionRequest(
            reason="已有进展，只剩一步", remaining_actions=1, estimated_extra_tokens=5_000,
            stage="tool_execution", progress_evidence={"completed_actions": 1}))
        seen.append((budget.policy, decision))
        return await original(message)

    agent.run_natural = run
    values = {"base_budget": 20_000, "hard_limit": 23_000,
              "finalization_reserve": 2_000, "planner_extension_limit": 5_000}
    with TestClient(create_app(agent=agent, settings=settings)) as client:
        client.patch("/api/settings/interface", json={"input_merge_seconds": 7, "allow_multi_model_calls": True})
        assert client.put("/api/settings/budget", json=values).json() == values
        assert client.get("/api/settings/budget").json() == values
        assert client.get("/api/settings/interface").json()["input_merge_seconds"] == 7
        assert client.get("/api/debug/budget-context").json()["configuration"]["base_budget"] == 20_000
        assert client.post("/api/chat", json={"message": "验证预算"}).status_code == 200
        policy, decision = seen[-1]
        assert policy.base_budget == 20_000 and policy.hard_limit == 23_000
        assert policy.finalization_reserve == 2_000 and policy.extension_1_limit == 5_000
        assert decision["approved_extra"] == 3_000  # Hard limit still clips approval.
        values["planner_extension_limit"] = 0
        assert client.put("/api/settings/budget", json=values).status_code == 200
        assert client.post("/api/chat", json={"message": "验证关闭申请"}).status_code == 200
        assert seen[-1][1]["approved_extra"] == 0
        assert seen[-1][1]["reason_code"] == "extension_limit"
        assert policy.extension_1_limit == 5_000  # Existing immutable policy wasn't changed.
        assert client.patch("/api/settings/interface", json={"force_non_fast_chat": True}).json()["request_budget"] == values
    restored = FakeAgent()
    restored.provider = SimpleNamespace(max_calls=12, max_total_tokens=100_000)
    with TestClient(create_app(agent=restored, settings=settings)) as client:
        assert client.get("/api/settings/budget").json() == values
        assert restored.provider.max_total_tokens == 20_000
        reset = client.delete("/api/settings/budget").json()
        assert reset == {"base_budget": 40_000, "hard_limit": 70_000,
                         "finalization_reserve": 3_000, "planner_extension_limit": 8_000}
        saved = client.get("/api/settings/interface").json()
        assert saved["request_budget"] is None and saved["allow_multi_model_calls"] is True
        assert restored.provider.budget_policy == settings.request_budget_policy


def test_invalid_or_unauthorized_budget_edit_is_atomic(tmp_path):
    settings = Settings(_env_file=None, perception_enabled=False,
                        interface_settings_path=str(tmp_path / "interface.json"))
    agent = FakeAgent()
    agent.provider = SimpleNamespace(max_calls=12, max_total_tokens=100_000)
    headers = {"X-Zhaoxi-Token": "budget-test"}
    values = {"base_budget": 20_000, "hard_limit": 30_000,
              "finalization_reserve": 2_000, "planner_extension_limit": 5_000}
    with TestClient(create_app(agent=agent, settings=settings, api_token="budget-test")) as client:
        assert client.put("/api/settings/budget", json=values).status_code == 401
        assert client.delete("/api/settings/budget").status_code == 401
        assert client.put("/api/settings/budget", headers=headers, json=values).status_code == 200
        policy = agent.provider.budget_policy
        path = tmp_path / "interface.json"
        saved_bytes = path.read_bytes()
        for patch in ({"hard_limit": 19_999}, {"finalization_reserve": 20_000},
                      {"base_budget": True}, {"base_budget": "20000"}, {"base_budget": 20_000.5},
                      {"planner_extension_limit": -1}, {"base_budget": 10_000_001}, {"unexpected": 1}):
            assert client.put("/api/settings/budget", headers=headers, json={**values, **patch}).status_code == 422
            assert path.read_bytes() == saved_bytes and agent.provider.budget_policy is policy
            assert client.get("/api/settings/budget", headers=headers).json() == values
