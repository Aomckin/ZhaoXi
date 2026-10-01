"""Validate and apply keyed operations to the living journal."""
from __future__ import annotations
import logging
import re
from datetime import datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo
from pydantic import BaseModel, Field, model_validator
from .models import CognitionThread, CurrentCognitionState, EvidenceRef, JournalItem
from .renderer import render_for_debug, render_for_desk, render_for_fast_chat
from .store import CurrentCognitionStore

logger = logging.getLogger("CURRENT_COGNITION")
_FORBIDDEN = re.compile(r"用户|该用户|用户自述|用户倾向|\d{1,2}:\d{2}|\d+(?:\.\d+)?(?:元|千卡|kcal)|[A-Za-z]:\\|早餐|午餐|晚餐|(?:明天|后天|今晚|下周\S{0,4}).{0,20}(?:面试|交|截止|开会|先修|提交|提醒)", re.I)
_PSYCHOLOGY = re.compile(r"人格障碍|隐藏动机|逃避.{0,12}压力|因为.{0,24}所以")
_ONE_OFF = re.compile(r"^(?:今天|刚才|刚刚).{0,12}(?:吃|喝|买|坐车|打车)")
_ALIASES = {"朝汐开发": "zhaoxi_runtime", "zhaoxi开发": "zhaoxi_runtime",
            "runtime_cleanup": "zhaoxi_runtime", "zhaoxi_runtime_cleanup": "zhaoxi_runtime",
            "秋招": "job_search", "校招": "job_search"}
_GENERIC = {"近期", "最近", "正在", "持续", "目前", "暗苟", "已经", "开始", "相关", "主要", "仍在", "仍然"}

def normalize_key(key: str) -> str:
    key = re.sub(r"[^\w\u4e00-\u9fff]+", "_", key.strip().casefold()).strip("_")[:60]
    return _ALIASES.get(key, key)

def _anchored(claim: str, evidence: str) -> bool:
    if not claim:
        return True
    pairs = {part[i:i+2] for part in re.findall(r"[\u4e00-\u9fff]{2,}", claim)
             for i in range(len(part)-1) if part[i:i+2] not in _GENERIC}
    seen = {part[i:i+2] for part in re.findall(r"[\u4e00-\u9fff]{2,}", evidence)
            for i in range(len(part)-1)}
    if pairs & seen:
        return True
    latin = set(re.findall(r"[a-zA-Z]{4,}", claim.casefold()))
    return bool(latin & set(re.findall(r"[a-zA-Z]{4,}", evidence.casefold())))

class OverviewOp(BaseModel):
    action: Literal["keep", "replace", "clear"] = "keep"
    value: str = Field(default="", max_length=160)

class ThreadOp(BaseModel):
    action: Literal["upsert", "remove", "resolve"]
    key: str = Field(min_length=2, max_length=60)
    title: str = Field(default="", max_length=40)
    summary: str = Field(default="", max_length=160)
    salience: float = Field(default=0.6, ge=0, le=1)
    evidence_message_ids: list[str] = Field(default_factory=list, max_length=8)

class ItemOp(BaseModel):
    action: Literal["upsert", "remove"]
    key: str = Field(min_length=2, max_length=60)
    text: str = Field(default="", max_length=80)
    evidence_message_ids: list[str] = Field(default_factory=list, max_length=4)

class CurrentCognitionPatch(BaseModel):
    decision: Literal["NO_CHANGE", "UPDATE"] = "NO_CHANGE"
    reason_code: str = "no_overall_change"
    reason: str = Field(default="", max_length=200)
    evidence_message_ids: list[str] = Field(default_factory=list, max_length=8)
    overview: OverviewOp = Field(default_factory=OverviewOp)
    thread_ops: list[ThreadOp] = Field(default_factory=list, max_length=8)
    change_ops: list[ItemOp] = Field(default_factory=list, max_length=6)
    watch_ops: list[ItemOp] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def validate_decision(self):
        edits = self.overview.action != "keep" or self.thread_ops or self.change_ops or self.watch_ops
        if self.decision == "NO_CHANGE" and edits:
            raise ValueError("NO_CHANGE cannot edit current cognition")
        if self.decision == "UPDATE" and not edits:
            raise ValueError("UPDATE requires an operation")
        return self

class CurrentCognitionService:
    def __init__(self, store: CurrentCognitionStore, *, timezone: str = "Asia/Shanghai") -> None:
        self.store = store
        self.timezone = ZoneInfo(timezone)
        self.last_maintenance = self.store.load().last_maintenance

    def state(self) -> CurrentCognitionState:
        return self.store.load()

    def snapshot(self, **_kwargs) -> str:
        return render_for_fast_chat(self.state())

    def render_for_fast_chat(self) -> str:
        return render_for_fast_chat(self.state())

    def render_for_desk(self) -> dict:
        return render_for_desk(self.state())

    def diagnostics(self) -> dict:
        state = self.state()
        now = datetime.now(self.timezone)
        explanations = [{"key": thread.key,
                         "why_exists": [ref.model_dump(mode="json") for ref in thread.source_refs],
                         "retention_reason": "recent_evidence" if thread.status == "active" else "cooling_until_day_7",
                         "days_since_evidence": round((now - thread.last_evidence_at).total_seconds() / 86400, 1)}
                        for thread in state.threads]
        return {"state": render_for_debug(state), "snapshot": render_for_fast_chat(state),
                "desk": render_for_desk(state), "thread_explanations": explanations,
                "last_maintenance": state.last_maintenance,
                "recent_decisions": state.recent_decisions}

    def _decay(self, state: CurrentCognitionState, now: datetime) -> dict:
        counts = {"threads_removed": 0, "threads_updated": 0}
        kept = []
        for thread in state.threads:
            days = (now - thread.last_evidence_at).total_seconds() / 86400
            if days >= 7 or thread.status == "resolved":
                counts["threads_removed"] += 1
                continue
            if days >= 3 and thread.status == "active":
                thread.status = "cooling"
                thread.salience = min(thread.salience, 0.45)
                thread.last_updated_at = now
                counts["threads_updated"] += 1
            kept.append(thread)
        state.threads = kept
        state.recent_changes = [x for x in state.recent_changes if now - x.updated_at < timedelta(days=3)]
        state.watch_items = [x for x in state.watch_items if now - x.updated_at < timedelta(days=7)]
        if not state.threads and state.overview and state.updated_at and now - state.updated_at >= timedelta(days=7):
            state.overview = ""
        return counts

    def apply(self, patch: CurrentCognitionPatch, *, source_by_id: dict[str, str],
              last_message_id: str, evidence_by_id: dict[str, str] | None = None,
              timestamp_by_id: dict[str, datetime] | None = None, provenance_by_id: dict[str, dict] | None = None,
              now: datetime | None = None,
              allow_empty_cursor: bool = False, advance_cursor: bool = True,
              model_call: bool = False, duration_ms: float = 0) -> CurrentCognitionState:
        now = now or datetime.now(self.timezone)
        evidence_by_id = evidence_by_id or {}
        timestamp_by_id = timestamp_by_id or {}
        provenance_by_id = provenance_by_id or {}
        state = self.state()
        before = state.model_dump(mode="json")
        counts = self._decay(state, now)
        counts.update({"threads_added": 0, "ops_count": 0})
        trusted = {key for key, source in source_by_id.items() if source in {"user", "owner_external"}}
        all_ids = [key for key in patch.evidence_message_ids if key in trusted]
        evidence = "\n".join(evidence_by_id.get(key, "") for key in all_ids)
        rejection = None
        claims = ([patch.overview.value] if patch.overview.action == "replace" else [])
        claims += [part for x in patch.thread_ops if x.action == "upsert" for part in (x.title, x.summary)]
        claims += [x.text for x in [*patch.change_ops, *patch.watch_ops] if x.action == "upsert"]
        proposed = " ".join(claims)
        if patch.decision == "UPDATE":
            if not all_ids:
                rejection = "missing_user_evidence"
            elif any(ids and not any(i in trusted for i in ids) for ids in
                     [*(x.evidence_message_ids for x in patch.thread_ops if x.action == "upsert"),
                      *(x.evidence_message_ids for x in [*patch.change_ops, *patch.watch_ops] if x.action == "upsert")]):
                rejection = "untrusted_operation_evidence"
            elif re.search(r"桌面.{0,8}(?:说|提到|发)|(?:说|提到|发).{0,8}桌面", proposed) and provenance_by_id and not any(provenance_by_id.get(i, {}).get("origin_channel")=="desktop" for i in all_ids):
                rejection = "unsupported_origin_claim"
            elif _FORBIDDEN.search(proposed):
                rejection = "tool_or_queryable_detail"
            elif _PSYCHOLOGY.search(proposed):
                rejection = "unsupported_psychology"
            elif _ONE_OFF.search(proposed):
                rejection = "one_off_detail"
            elif any(not _anchored(claim, evidence) for claim in claims):
                rejection = "unsupported_claim"
            elif any(x.action == "upsert" and (not x.title.strip() or not x.summary.strip()) for x in patch.thread_ops):
                rejection = "empty_thread"
            elif any(x.action == "upsert" and not x.text.strip() for x in [*patch.change_ops, *patch.watch_ops]):
                rejection = "empty_item"
        if not rejection and patch.decision == "UPDATE":
            if patch.overview.action == "replace":
                state.overview = patch.overview.value.strip()
                state.overview_source_refs = [EvidenceRef(message_id=i, event_id=i, timestamp=timestamp_by_id.get(i), source=source_by_id[i], provenance=provenance_by_id.get(i, {})) for i in all_ids]
                counts["ops_count"] += 1
            elif patch.overview.action == "clear":
                state.overview = ""
                state.overview_source_refs = []
                counts["ops_count"] += 1
            for op in patch.thread_ops:
                key = normalize_key(op.key)
                same = next((t for t in state.threads if normalize_key(t.key) == key or
                             (op.title and normalize_key(t.title) == normalize_key(op.title))), None)
                if op.action in {"remove", "resolve"}:
                    if same:
                        state.threads.remove(same)
                        counts["threads_removed"] += 1
                        counts["ops_count"] += 1
                    continue
                refs = [EvidenceRef(message_id=i, event_id=i, timestamp=timestamp_by_id.get(i), source=source_by_id[i],
                                    provenance=provenance_by_id.get(i, {}))
                        for i in (op.evidence_message_ids or all_ids) if i in trusted]
                if same:
                    same.title, same.summary, same.salience = op.title.strip(), op.summary.strip(), op.salience
                    same.status, same.last_updated_at, same.last_evidence_at = "active", now, now
                    same.source_refs = (same.source_refs + refs)[-8:]
                    counts["threads_updated"] += 1
                else:
                    state.threads.append(CognitionThread(key=key, title=op.title.strip(), summary=op.summary.strip(),
                        salience=op.salience, first_seen_at=now, last_updated_at=now, last_evidence_at=now,
                        source_refs=refs))
                    counts["threads_added"] += 1
                counts["ops_count"] += 1
            for ops, collection in ((patch.change_ops, state.recent_changes),
                                    (patch.watch_ops, state.watch_items)):
                for op in ops:
                    key = normalize_key(op.key)
                    same = next((x for x in collection if normalize_key(x.key) == key), None)
                    if op.action == "remove":
                        if same:
                            collection.remove(same)
                            counts["ops_count"] += 1
                        continue
                    refs = [EvidenceRef(message_id=i, event_id=i, timestamp=timestamp_by_id.get(i), source=source_by_id[i],
                                    provenance=provenance_by_id.get(i, {}))
                            for i in (op.evidence_message_ids or all_ids) if i in trusted]
                    if same:
                        same.text, same.updated_at = op.text.strip(), now
                        same.source_refs = (same.source_refs + refs)[-4:]
                    else:
                        collection.append(JournalItem(key=key, text=op.text.strip(), created_at=now,
                                                      updated_at=now, source_refs=refs))
                    counts["ops_count"] += 1
        state.threads.sort(key=lambda t: (t.status != "active", -t.salience, -t.last_evidence_at.timestamp()))
        active = [x for x in state.threads if x.status == "active"][:4]
        cooling = [x for x in state.threads if x.status == "cooling"][:3]
        state.threads = active + cooling
        state.recent_changes = sorted(state.recent_changes, key=lambda x: x.updated_at, reverse=True)[:3]
        state.watch_items = sorted(state.watch_items, key=lambda x: x.updated_at, reverse=True)[:3]
        changed = state.model_dump(mode="json") != before
        if changed:
            state.version = max(2, state.version + 1)
            state.updated_at = now
        decision = "UPDATE" if changed else "NO_CHANGE"
        if advance_cursor and not rejection and (state.overview or state.threads or state.recent_changes or state.watch_items or allow_empty_cursor):
            state.last_processed_message_id = last_message_id
        record = {"decision": decision, "reason_code": patch.reason_code, "reason": patch.reason or patch.reason_code,
                  "rejection": rejection, "at": now.isoformat(), "evidence_message_ids": all_ids,
                  "model_call": model_call, "duration_ms": round(duration_ms, 2), **counts,
                  "operations": patch.model_dump(mode="json")}
        state.last_maintenance = record
        state.recent_decisions = [*state.recent_decisions, {k: v for k, v in record.items() if k != "operations"}][-10:]
        self.store.save(state)
        self.last_maintenance = record
        logger.info("COGNITION_%s version=%d rejection=%s ops=%d", decision, state.version, rejection, counts["ops_count"])
        return state

    def record_failure(self, exc: Exception, *, details: dict | None = None) -> None:
        state = self.state()
        record = {"decision": "FAILED", "error_type": type(exc).__name__,
                  "at": datetime.now(self.timezone).isoformat(), **(details or {})}
        state.last_maintenance = record
        self.last_maintenance = record
        self.store.save(state)
