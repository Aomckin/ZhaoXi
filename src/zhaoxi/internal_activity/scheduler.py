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
