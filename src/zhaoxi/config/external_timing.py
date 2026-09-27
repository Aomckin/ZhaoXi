"""Live timing controls shared by Desktop settings and external adapters."""
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExternalTiming:
    debounce_seconds: float = 5.0
    reply_interval_seconds: float | None = None


def load_external_timing(path: str | Path) -> ExternalTiming:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        debounce = float(value.get("external_input_debounce_seconds", 5))
        configured_interval = value.get("external_reply_interval_seconds")
        interval = float(configured_interval) if configured_interval is not None else None
        if not (0 <= debounce <= 15 and (interval is None or 0 <= interval <= 5)):
            raise ValueError("external timing out of range")
        return ExternalTiming(debounce, interval)
    except (OSError, ValueError, TypeError, AttributeError):
        return ExternalTiming()
