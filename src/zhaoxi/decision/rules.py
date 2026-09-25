"""Small, editable rule store with bounded domain and keyword retrieval."""

import re
from pathlib import Path

from .models import DecisionRule


class RuleStore:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def get(self, rule_id: str) -> DecisionRule | None:
        path = self.directory / f"{rule_id}.json"
        if not path.is_file() or path.stem != rule_id:
            return None
        return DecisionRule.model_validate_json(path.read_text(encoding="utf-8"))

    def retrieve(self, text: str, domain: str, *, limit: int = 5) -> list[DecisionRule]:
        scored = []
        for path in self.directory.glob("*.json"):
            rule = DecisionRule.model_validate_json(path.read_text(encoding="utf-8"))
            if rule.id != path.stem:
                raise ValueError(f"Decision rule ID mismatch: {path.name}")
            if rule.required_pattern and not re.search(rule.required_pattern, text, re.I):
                continue
            hits = sum(1 for keyword in [*rule.keywords, *rule.tags] if keyword and keyword.casefold() in text.casefold())
            if not hits or rule.domain not in {domain, "general"}:
                continue
            scored.append((hits * 2 + (3 if rule.domain == domain else 0), rule))
        scored.sort(key=lambda pair: (-pair[0], pair[1].id))
        return [rule for _, rule in scored[:limit]]
