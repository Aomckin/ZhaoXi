"""Presentation-only timezone conversion owned by LifeHUD-Tool."""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel


class LifeHudTimeDisplay:
    """Serialize API models for the model/UI without mutating UTC source values."""

    def __init__(self, timezone_name: str) -> None:
        try:
            self.timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"未知 Life HUD 展示时区：{timezone_name}") from exc
        self.timezone_name = timezone_name

    def dump(self, value: BaseModel) -> dict[str, Any]:
        return self._convert(value.model_dump(mode="python"))

    def _convert(self, value: Any) -> Any:
        if isinstance(value, datetime):
            return value.astimezone(self.timezone).isoformat()
        if isinstance(value, dict):
            return {key: self._convert(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._convert(item) for item in value]
        return value
