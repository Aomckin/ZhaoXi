"""Structured inputs and outputs for one decision."""

from datetime import datetime
from enum import StrEnum
import re
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class DecisionLevel(StrEnum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"


class DecisionRule(BaseModel):
    id: str
    domain: str
    tags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    trigger: str
    required_pattern: str | None = None
    default: str
    level_hint: DecisionLevel = DecisionLevel.L1
    reasons: list[str] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)
    auto_execute: bool = False
    source: dict[str, str]


class DecisionContext(BaseModel):
    current_time: datetime
    user_request: str
    today_mainline: str | None = None
    schedule: list[str] = Field(default_factory=list)
    short_term_note: str | None = None
    relevant_memories: list[str] = Field(default_factory=list)
    matched_rules: list[DecisionRule] = Field(default_factory=list)
    available_tools: list[str] = Field(default_factory=list)
    current_constraints: list[str] = Field(default_factory=list)
    decision_mode: str = "normal"


class DecisionProposal(BaseModel):
    level: DecisionLevel
    domain: str
    decision: str = Field(default="", max_length=200)
    reasons: list[str] = Field(default_factory=list, max_length=2)
    exception: str | None = None
    conflicts: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    core_question: str | None = None
    options: list[str] = Field(default_factory=list, max_length=3)
    action: str | None = None
    rule_ids: list[str] = Field(default_factory=list)
    uncertain: bool = False
    unknown_side_effects: bool = False


class DecisionResult(DecisionProposal):
    verdict: str
    decision_id: str = Field(default_factory=lambda: uuid4().hex)
    can_auto_execute: bool = False
    constraints: list[str] = Field(default_factory=list)
    upgraded_from: DecisionLevel | None = None
    upgrade_reasons: list[str] = Field(default_factory=list)
    context_sources: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_direction(self) -> "DecisionResult":
        if self.level == DecisionLevel.L2:
            if self.verdict != "交由用户决定" or self.decision:
                raise ValueError("L2 must defer without a recommendation")
        elif not is_directional_verdict(self.verdict) or self.decision != self.verdict:
            raise ValueError("L0/L1 verdict must be a concrete direction, not a question")
        return self


_QUESTION = re.compile(r"[?？]|是否|要不要|该不该|能不能|可不可以|值不值得|选哪个|怎么选|怎么办|哪一个|(?:开不|去不|做不|买不|接不)[\u4e00-\u9fff]")
_NON_VERDICT = re.compile(r"^(?:建议[:：])?\s*(?:看情况|再看看|你决定|由你决定|随你|都可以|都行|不确定|待定)\s*[。！!]*$")


def is_directional_verdict(value: str) -> bool:
    text = value.strip()
    return bool(text and not _QUESTION.search(text) and not _NON_VERDICT.fullmatch(text))
