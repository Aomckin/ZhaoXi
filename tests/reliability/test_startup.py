from zhaoxi.config.settings import Settings
from zhaoxi.reliability.startup import startup_diagnostics


def test_startup_diagnostics_explains_missing_model_without_exposing_secrets(tmp_path):
    settings = Settings(
        model_api_key="",
        model_name="",
        memory_db_path=str(tmp_path / "data" / "memory.db"),
    )
    result = startup_diagnostics(settings, tool_root=tmp_path / "no-tools")

    assert result["status"] == "needs_configuration"
    assert result["checks"]["model"]["code"] == "model_config_missing"
    assert "ZHAOXI_MODEL_API_KEY" in result["checks"]["model"]["action"]


def test_startup_diagnostics_lists_lifehud_package_without_user_content(tmp_path, monkeypatch):
    monkeypatch.setenv("ZHAOXI_TOOL_LIFEHUD_ENABLED", "true")
    settings = Settings(
        model_api_key="secret-canary",
        model_name="test-model",
        memory_db_path=str(tmp_path / "memory.db"),
    )
    result = startup_diagnostics(settings)

    assert result["status"] == "ready"
    package = next(item for item in result["tool_packages"] if item["id"] == "lifehud-tool")
    assert package["id"] == "lifehud-tool"
    assert package["version"] == "1.1.0"
    assert package["installed"] is package["enabled"] is package["configured"] is True
    assert package["tools"] == ["lifehud"]
    assert package["requires_sdk"] == ">=1,<2"
    assert "state_signal_provider" in package["capabilities"]
    assert isinstance(package["reachable"], bool)
    assert isinstance(package["healthy"], bool)
    assert "secret-canary" not in str(result)
