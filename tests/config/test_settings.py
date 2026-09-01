import pytest
from pydantic import ValidationError

from zhaoxi.config.settings import Settings


def test_planner_timeout_and_attempt_limits_are_cross_validated():
    with pytest.raises(ValidationError, match="step timeout"):
        Settings(
            _env_file=None,
            planner_step_timeout_seconds=20,
            planner_total_timeout_seconds=10,
        )
    with pytest.raises(ValidationError, match="尝试次数"):
        Settings(_env_file=None, planner_max_attempts_per_step=3, planner_max_steps=2)


def test_memory_lifecycle_thresholds_are_ordered():
    with pytest.raises(ValidationError, match="importance"):
        Settings(
            _env_file=None,
            memory_importance_forget_threshold=0.8,
            memory_importance_keep_threshold=0.7,
        )


def test_proactive_night_window_must_have_duration():
    with pytest.raises(ValidationError, match="proactive night"):
        Settings(
            _env_file=None,
            proactive_night_start_hour=8,
            proactive_night_end_hour=8,
        )
    with pytest.raises(ValidationError, match="relevance"):
        Settings(
            _env_file=None,
            memory_relevance_forget_threshold=0.7,
            memory_relevance_active_threshold=0.6,
        )


def test_voice_provider_and_audio_limits_are_validated():
    with pytest.raises(ValidationError, match="stt provider"):
        Settings(_env_file=None, stt_provider="unknown")
    with pytest.raises(ValidationError, match="tts provider"):
        Settings(_env_file=None, tts_provider="unknown")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, voice_max_seconds=0)
    configured = Settings(
        _env_file=None,
        voice_enabled=True,
        stt_provider="openai-compatible",
        tts_provider="windows",
    )
    assert configured.voice_language == "zh-CN"
    assert not configured.voice_auto_send


def test_reflection_defaults_are_bounded_and_automatic_delivery_is_opt_in():
    settings = Settings(_env_file=None)
    assert settings.reflection_enabled
    assert settings.reflection_db_path == ".zhaoxi/reflection.db"
    assert settings.reflection_timezone == "Asia/Shanghai"
    assert settings.reflection_max_evidence == 200
    assert not settings.reflection_auto_daily
    assert not settings.reflection_auto_weekly
    assert not settings.reflection_auto_monthly
    assert not settings.reflection_notify

    with pytest.raises(ValidationError):
        Settings(_env_file=None, reflection_max_evidence=0)
