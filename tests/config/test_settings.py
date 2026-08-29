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
