"""Append-only summaries and human overrides; formal rules stay untouched."""

import json
from datetime import datetime, timezone
from pathlib import Path

from .models import DecisionResult


class DecisionRecorder:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def _append(self, name: str, row: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / name).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _rows(self, name: str) -> list[dict]:
        path = self.directory / name
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def record(self, result: DecisionResult, summary: str) -> None:
        self._append("decision_log.jsonl", {
            "decision_id": result.decision_id, "timestamp": datetime.now(timezone.utc).isoformat(),
            "domain": result.domain, "summary": summary[:160], "level": result.level.value,
            "matched_rules": result.rule_ids, "decision": result.decision[:200],
            "user_final_choice": None, "overridden": False, "outcome": None,
        })

    def override(self, decision_id: str, final: str, reason: str | None = None) -> dict:
        original = next((row for row in reversed(self._rows("decision_log.jsonl"))
                         if row["decision_id"] == decision_id), None)
        if original is None:
            raise ValueError("Unknown decision ID")
        row = {"decision_id": decision_id, "original": original["decision"], "final": final[:200],
               "reason": reason[:200] if reason else None, "timestamp": datetime.now(timezone.utc).isoformat(),
               "rule_ids": original["matched_rules"]}
        self._append("override_log.jsonl", row)
        overrides = self._rows("override_log.jsonl")
        candidates = {candidate["rule_id"] for candidate in self._rows("rule_candidates.jsonl")}
        for rule_id in row["rule_ids"]:
            count = sum(rule_id in item["rule_ids"] for item in overrides)
            if count >= 3 and rule_id not in candidates:
                self._append("rule_candidates.jsonl", {"rule_id": rule_id, "signal": "frequent_override",
                                                        "count": count, "suggestion": "review_rule"})
        return row

    def candidates(self) -> list[dict]:
        return self._rows("rule_candidates.jsonl")[-20:]
