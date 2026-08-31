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
