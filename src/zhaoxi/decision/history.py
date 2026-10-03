"""Small append-only choice summaries. Episodes never become preference rules."""

from datetime import UTC, datetime
import json
import logging
from pathlib import Path
from threading import RLock

from .models import DecisionAwarenessTrace


class ChoiceHistory:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self._lock = RLock()

    def _rows(self, name: str) -> list[dict]:
        path = self.directory / name
        if not path.exists():
            return []
        rows = []
        # Keep per-turn pending-choice reads bounded even after years of episodes.
        # The full append-only files remain available to backups and offline work.
        with path.open("rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - 512_000))
            if size > 512_000:
                stream.readline()
            content = stream.read().decode("utf-8")
        for line in content.splitlines():
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
            except ValueError:
                logging.getLogger("DECISION").warning("ignoring invalid choice history row")
        return rows

    def _append(self, row: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / "choice_history.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    def record(self, decision_id: str, trace: DecisionAwarenessTrace, summary: str,
               *, scope: str) -> dict:
        row = {"decision_id": decision_id, "schema_version": 2,
               "timestamp": datetime.now(UTC).isoformat(), "scope": scope,
               "summary": summary[:160], "mode": trace.mode.value,
               "suggestion": trace.agent_recommendation,
               "predicted_user_choice": trace.predicted_user_choice,
               "context_refs": trace.context_refs, "context_sources": trace.context_sources,
               "principle_ids": trace.principle_ids, "guard_flags": trace.guard_flags,
               "user_final_choice": None, "overridden": False, "outcome": None}
        with self._lock:
            self._append(row)
        return row

    def list(self, *, limit: int = 20, scope: str | None = None) -> list[dict]:
        with self._lock:
            choices = {}
            for old in self._rows("decision_log.jsonl"):
                if not old.get("decision_id"):
                    continue
                choices[old["decision_id"]] = {**old, "schema_version": 1,
                    "mode": {"L0": "PICK", "L1": "ADVISE", "L2": "FRAME"}.get(old.get("level"), "NONE"),
                    "suggestion": old.get("decision"), "context_refs": [], "scope": "legacy"}
            for override in self._rows("override_log.jsonl"):
                if original := choices.get(override.get("decision_id")):
                    original.update(user_final_choice=override.get("final"), overridden=True)
            for row in self._rows("choice_history.jsonl"):
                identity = row.get("decision_id")
                if row.get("event") == "feedback":
                    if original := choices.get(identity):
                        original.update({key: row.get(key) for key in
                            ("user_final_choice", "overridden", "outcome")})
                elif identity:
                    choices[identity] = row
            rows = [row for row in choices.values() if scope is None or row.get("scope") == scope]
            rows.sort(key=lambda row: row.get("timestamp", ""), reverse=True)
            return rows[:max(1, min(limit, 100))]

    def feedback(self, decision_id: str, final: str, *, scope: str,
                 overridden: bool = False, outcome: str | None = None) -> dict:
        with self._lock:
            if not any(row["decision_id"] == decision_id for row in self.list(limit=100, scope=scope)):
                raise ValueError("Unknown choice in this conversation")
            row = {"event": "feedback", "schema_version": 2, "decision_id": decision_id,
                   "timestamp": datetime.now(UTC).isoformat(), "scope": scope,
                   "user_final_choice": final[:200], "overridden": overridden,
                   "outcome": outcome[:200] if outcome else None}
            self._append(row)
            return row

    def retrieve(self, query: str, *, scope: str, limit: int = 5) -> list[dict]:
        from .principles import relevance
        ranked = [(relevance(query, row.get("summary", "") + " " + (row.get("suggestion") or "")), row)
                  for row in self.list(limit=100, scope=scope)]
        ranked.sort(key=lambda pair: -pair[0])
        return [row for score, row in ranked if score > 0][:limit]
