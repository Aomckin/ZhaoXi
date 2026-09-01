"""Small, dependency-free, low-cardinality process metrics."""

from __future__ import annotations

from collections import Counter, defaultdict
from threading import Lock
from time import monotonic


class MetricRegistry:
    """Collect counters and duration aggregates without user-derived labels."""

    def __init__(self) -> None:
        self._started = monotonic()
        self._counters: Counter[str] = Counter()
        self._duration_count: Counter[str] = Counter()
        self._duration_total: dict[str, float] = defaultdict(float)
        self._lock = Lock()

    def increment(self, name: str, amount: int = 1) -> None:
        self._validate_name(name)
        if amount < 0:
            raise ValueError("counter amount 不能为负数")
        with self._lock:
            self._counters[name] += amount

    def observe_duration(self, name: str, seconds: float) -> None:
        self._validate_name(name)
        if seconds < 0:
            raise ValueError("duration 不能为负数")
        with self._lock:
            self._duration_count[name] += 1
            self._duration_total[name] += seconds

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            counters = dict(sorted(self._counters.items()))
            durations = {
                name: {
                    "count": self._duration_count[name],
                    "total_seconds": round(total, 6),
                    "average_seconds": round(total / self._duration_count[name], 6),
                }
                for name, total in sorted(self._duration_total.items())
            }
        return {
            "uptime_seconds": round(max(0.0, monotonic() - self._started), 3),
            "counters": counters,
            "durations": durations,
        }

    @staticmethod
    def _validate_name(name: str) -> None:
        if not name or len(name) > 128 or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_." for char in name):
            raise ValueError("metric name 只能包含小写字母、数字、点和下划线")
