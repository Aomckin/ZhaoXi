"""Validate and apply small, evidence-bound edits to the live journal."""

from __future__ import annotations

import logging
import json
import re
from datetime import datetime, timedelta
from difflib import unified_diff
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator

from .models import CurrentCognitionState, TopicObservation
from .renderer import render
from .store import CurrentCognitionStore

logger = logging.getLogger("CURRENT_COGNITION")


class NarrativeEdit(BaseModel):
    from_text: str = Field(alias="from", max_length=700)
    to: str = Field(max_length=700)


class ObservationProposal(BaseModel):
    key: str = Field(min_length=2, max_length=60)
    source_message_id: str


class CurrentCognitionPatch(BaseModel):
    decision: Literal["NO_CHANGE", "UPDATE"]
    reason_code: Literal["no_overall_change", "ongoing_mainline", "state_change", "repeated_recent_theme", "cross_context"] = "no_overall_change"
    reason: str = Field(default="", max_length=200)
    evidence_message_ids: list[str] = Field(default_factory=list, max_length=8)
    narrative_patch: list[NarrativeEdit] = Field(default_factory=list, max_length=3)
    threads_add: list[str] = Field(default_factory=list, max_length=4)
    threads_remove: list[str] = Field(default_factory=list, max_length=4)
    attention_add: list[str] = Field(default_factory=list, max_length=3)
    attention_remove: list[str] = Field(default_factory=list, max_length=3)
    observations: list[ObservationProposal] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def validate_decision(self):
        edits = (self.narrative_patch or self.threads_add or self.threads_remove or
                 self.attention_add or self.attention_remove)
        if self.decision == "NO_CHANGE" and edits:
            raise ValueError("NO_CHANGE cannot edit current cognition")
        if self.decision == "UPDATE" and not edits:
            raise ValueError("UPDATE requires an edit")
        return self


_NOISE = re.compile(r"(?:[A-Za-z]:\\|[/\\][\w.-]+\.(?:db|md|py|json|log|html)|\b(?:SQL|Navicat|SQLite|API|Debug)\b|数据库|文件路径|工具调用|具体金额|\d{1,2}:\d{2}|\d+(?:\.\d+)?元|\d+(?:\.\d+)?(?:千卡|kcal)|睡眠.{0,8}\d+(?:\.\d+)?小时)", re.I)
_PSYCHOLOGY = re.compile(r"逃避|心理诊断|人格障碍|缓解.{0,8}压力|因为.{0,30}所以")
_ONE_OFF = re.compile(r"(?:吃了|吃饭|早餐|午餐|晚餐|买了|点了外卖|花了|打车|坐车)")
_GENERIC_ANCHORS = {"近期", "最近", "正在", "持续", "目前", "用户", "暗苟", "已经", "开始", "相关", "主要", "仍在", "仍然"}


def _has_evidence_anchor(claim: str, evidence: str) -> bool:
    """Require at least one concrete lexical anchor; reject an unrelated model invention."""
    if not claim.strip():
        return True  # A removal need not introduce a new fact.
    pairs = {word for phrase in re.findall(r"[\u4e00-\u9fff]{2,}", claim)
             for word in (phrase[index:index + 2] for index in range(len(phrase) - 1))
             if word not in _GENERIC_ANCHORS}
    if pairs.intersection({word for phrase in re.findall(r"[\u4e00-\u9fff]{2,}", evidence)
                           for word in (phrase[index:index + 2] for index in range(len(phrase) - 1))}):
        return True
    if "秋招" in claim and re.search(r"校招|面试|笔试|宣讲|岗位|网申|投递", evidence):
        return True
    if "朝汐" in claim and re.search(r"Zhaoxi|朝汐", evidence, re.I):
        return True
    return False


class CurrentCognitionService:
    def __init__(self, store: CurrentCognitionStore, *, timezone: str = "Asia/Shanghai") -> None:
        self.store = store
        self.timezone = ZoneInfo(timezone)
        self.last_maintenance = self.store.load().last_maintenance

    def state(self) -> CurrentCognitionState:
        return self.store.load()

    def snapshot(self, **_kwargs) -> str:
        return render(self.state())

    def diagnostics(self) -> dict:
        state = self.state()
        return {"state": state.model_dump(mode="json"), "snapshot": render(state),
                "updated_at": state.updated_at.isoformat() if state.updated_at else None,
                "last_processed_message_id": state.last_processed_message_id,
                "last_maintenance": state.last_maintenance,
                "recent_decisions": state.recent_decisions}

    def apply(self, patch: CurrentCognitionPatch, *, source_by_id: dict[str, str],
              last_message_id: str, evidence_by_id: dict[str, str] | None = None,
              now: datetime | None = None) -> CurrentCognitionState:
        now = now or datetime.now(self.timezone)
        state = self.state()
        evidence_by_id = evidence_by_id or {}
        # Observation counters are only a recent trend signal, not durable memory.
        observations = {item.key: item for item in state.observations
                        if now - item.last_seen_at <= timedelta(days=7)}
        for proposal in patch.observations:
            if source_by_id.get(proposal.source_message_id) != "user":
                continue
            item = observations.get(proposal.key)
            if item is None:
                item = TopicObservation(key=proposal.key, last_seen_at=now)
                observations[proposal.key] = item
            if proposal.source_message_id not in item.message_ids:
                item.count += 1
                item.message_ids = [*item.message_ids, proposal.source_message_id][-8:]
                item.last_seen_at = now
        state.observations = sorted(observations.values(), key=lambda item: item.last_seen_at, reverse=True)[:12]

        before = state.narrative
        before_threads = state.ongoing_threads.copy()
        before_attention = state.attention.copy()
        decision = patch.decision
        rejection = None
        if decision == "UPDATE":
            trusted = [message_id for message_id in patch.evidence_message_ids
                       if source_by_id.get(message_id) == "user"]
            evidence = "\n".join(evidence_by_id.get(message_id, "") for message_id in trusted)
            proposed = " ".join([edit.to for edit in patch.narrative_patch] + patch.threads_add + patch.attention_add)
            if not trusted:
                rejection = "missing_user_evidence"
            elif _NOISE.search(proposed):
                rejection = "tool_or_queryable_detail"
            elif _PSYCHOLOGY.search(proposed) and not all(claim in evidence for claim in _PSYCHOLOGY.findall(proposed)):
                rejection = "unsupported_psychology"
            elif _ONE_OFF.search(proposed):
                rejection = "one_off_detail"
            elif any(not _has_evidence_anchor(claim, evidence)
                     for claim in [edit.to for edit in patch.narrative_patch] + patch.threads_add + patch.attention_add):
                rejection = "unsupported_claim"
            elif patch.reason_code == "repeated_recent_theme" and not any(
                item.count >= 3 and item.key in proposed for item in state.observations):
                rejection = "insufficient_repetition"
            else:
                narrative = before
                for edit in patch.narrative_patch:
                    if edit.from_text:
                        if edit.from_text not in narrative:
                            rejection = "patch_target_missing"
                            break
                        narrative = narrative.replace(edit.from_text, edit.to, 1)
                    elif not narrative.strip():
                        narrative = edit.to
                    else:
                        rejection = "append_without_target"
                        break
                threads = [x for x in state.ongoing_threads if x not in patch.threads_remove]
                attention = [x for x in state.attention if x not in patch.attention_remove]
                threads = list(dict.fromkeys([*threads, *patch.threads_add]))
                attention = list(dict.fromkeys([*attention, *patch.attention_add]))
                if not rejection and (len(narrative) > 700 or len(threads) > 4 or len(attention) > 3):
                    rejection = "capacity_exceeded"
                if not rejection:
                    state.narrative = narrative.strip()
                    state.ongoing_threads = threads
                    state.attention = attention
                    if (state.narrative, threads, attention) != (before, before_threads, before_attention):
                        state.version += 1
                        state.updated_at = now
                    else:
                        decision = "NO_CHANGE"
        if rejection:
            decision = "NO_CHANGE"
        before_view = json.dumps({"narrative": before, "ongoing_threads": before_threads,
                                  "attention": before_attention}, ensure_ascii=False, indent=2)
        after_view = json.dumps({"narrative": state.narrative, "ongoing_threads": state.ongoing_threads,
                                 "attention": state.attention}, ensure_ascii=False, indent=2)
        diff = "\n".join(unified_diff(before_view.splitlines(), after_view.splitlines(), lineterm=""))[:1500]
        record = {"decision": decision, "reason_code": patch.reason_code,
                  "reason": patch.reason or patch.reason_code, "rejection": rejection, "at": now.isoformat(),
                  "evidence_message_ids": patch.evidence_message_ids, "before_after_diff": diff,
                  "patch": patch.model_dump(mode="json", by_alias=True)}
        state.last_processed_message_id = last_message_id
        state.last_maintenance = record
        state.recent_decisions = [*state.recent_decisions, {k: v for k, v in record.items() if k != "patch"}][-10:]
        self.store.save(state)
        self.last_maintenance = record
        logger.info("COGNITION_%s version=%d rejection=%s", decision, state.version, rejection)
        return state

    def record_failure(self, exc: Exception, *, details: dict | None = None) -> None:
        state = self.state()
        record = {"decision": "FAILED", "error_type": type(exc).__name__, **(details or {})}
        state.last_maintenance = record
        self.last_maintenance = record
        self.store.save(state)
