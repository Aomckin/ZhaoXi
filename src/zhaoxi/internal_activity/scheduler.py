"""Priority and per-tick resource selection for due internal activities."""

from __future__ import annotations


class ActivityScheduler:
    def __init__(self, max_llm: int, max_local: int) -> None:
        self.max_llm = max_llm
        self.max_local = max_local

    def select(self, candidates: list[tuple[int, str, str, str]], *, forced: bool = False):
        llm = local = 0
        for priority, name, kind, reason in candidates:
            if not forced and ((kind == "llm" and llm >= self.max_llm)
                               or (kind == "local" and local >= self.max_local)):
                yield name, kind, reason, False
                continue
            llm += kind == "llm"
            local += kind == "local"
            yield name, kind, reason, True


    def select_registered(self, candidates, registry, budget, *, maintenance_pending=False):
        """Priority-ordered selections share composite resource reservations."""
        debt = maintenance_pending or any(registry.get(name).priority >= 60 or reason in {"bootstrap", "recovery"} for _, name, _, reason in candidates)
        for priority, name, kind, reason in candidates:
            spec = registry.get(name)
            if debt and spec.category.value in {"LEISURE", "SOCIAL"}:
                yield name, kind, reason, "maintenance_pending"
            elif not budget.reserve(spec, kind):
                yield name, kind, reason, "budget"
            else:
                yield name, kind, reason, None
