"""Apply validated patches, merge updates and age weak recent signals."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from .models import Category, LIMITS, ShortTermMemoryItem, ShortTermMemoryState, Source, Status
from .renderer import render
from .store import ShortTermMemoryStore

logger = logging.getLogger("STM")


def _grounded(content: str, source: Source, evidence: str) -> bool:
    """Reject unsupported psychological/causal claims, even with a valid source ID."""
    if source != Source.USER and re.search(r"逃避|心理|人格|缓解.{0,8}压力|因为.{0,30}所以", content):
        return False
    claims = re.findall(r"逃避|心理|人格|缓解.{0,8}压力|因为.{0,30}所以", content)
    return not claims or all(claim in evidence for claim in claims)


class ItemProposal(BaseModel):
    category: Category
    content: str = Field(min_length=1, max_length=240)
    source: Source
    source_message_id: str
    confidence: float = Field(default=1.0, ge=0, le=1)


class ItemUpdate(BaseModel):
    id: str
    content: str = Field(min_length=1, max_length=240)
    source: Source
    source_message_id: str


class Reinforcement(BaseModel):
    id: str
    source_message_id: str


class ShortTermMemoryPatch(BaseModel):
    action: str = Field(pattern="^(NO_CHANGE|UPDATE)$")
    add: list[ItemProposal] = Field(default_factory=list, max_length=10)
    update: list[ItemUpdate] = Field(default_factory=list, max_length=10)
    reinforce: list[Reinforcement] = Field(default_factory=list, max_length=10)
    fade: list[str] = Field(default_factory=list, max_length=10)
    remove: list[str] = Field(default_factory=list, max_length=10)


class ShortTermMemoryService:
    def __init__(self, store: ShortTermMemoryStore, *, timezone: str = "Asia/Shanghai") -> None:
        self.store = store
        self.timezone = ZoneInfo(timezone)
        self.last_maintenance: dict = self.store.load().last_maintenance

    def state(self) -> ShortTermMemoryState:
        return self.store.load()

    def snapshot(self, **_kwargs) -> str:
        value = render(self.state())
        logger.debug("STM_RENDERED chars=%d", len(value))
        return value

    def diagnostics(self) -> dict:
        state = self.state()
        return {"state": state.model_dump(mode="json"), "snapshot": render(state),
                "updated_at": state.updated_at.isoformat() if state.updated_at else None,
                "last_processed_message_id": state.last_processed_message_id,
                "last_maintenance": self.last_maintenance}

    def apply(self, patch: ShortTermMemoryPatch, *, source_by_id: dict[str, str], last_message_id: str,
              evidence_by_id: dict[str, str] | None = None,
              now: datetime | None = None) -> ShortTermMemoryState:
        now = now or datetime.now(self.timezone)
        state = self.state()
        items = {item.id: item for item in state.items}
        changed = False
        if patch.action == "UPDATE":
            for item_id in patch.remove:
                if items.pop(item_id, None):
                    changed = True
                    logger.info("STM_ITEM_REMOVED id=%s", item_id)
            for item_id in patch.fade:
                if item_id in items and items[item_id].status != Status.FADING:
                    items[item_id].status = Status.FADING
                    changed = True
                    logger.info("STM_ITEM_FADED id=%s", item_id)
            for proposal in patch.update:
                item = items.get(proposal.id)
                if (item and source_by_id.get(proposal.source_message_id) == proposal.source.value
                    and proposal.source in {Source.USER, Source.TOOL}
                    and not (item.source == Source.USER and proposal.source == Source.TOOL)
                    and _grounded(proposal.content, proposal.source, (evidence_by_id or {}).get(proposal.source_message_id, ""))):
                    item.content = proposal.content.strip()
                    item.source = proposal.source
                    item.last_seen_at = item.last_reinforced_at = now
                    if proposal.source_message_id not in item.source_message_ids:
                        item.reinforcements += 1
                    item.status = Status.ACTIVE
                    item.source_message_ids = list(dict.fromkeys([*item.source_message_ids, proposal.source_message_id]))[-8:]
                    changed = True
                    logger.info("STM_ITEM_UPDATED id=%s category=%s", item.id, item.category.value)
            for proposal in patch.reinforce:
                item = items.get(proposal.id)
                if item and source_by_id.get(proposal.source_message_id) in {"user", "tool"} and proposal.source_message_id not in item.source_message_ids:
                    item.last_seen_at = item.last_reinforced_at = now
                    item.reinforcements += 1
                    item.status = Status.ACTIVE
                    item.source_message_ids = list(dict.fromkeys([*item.source_message_ids, proposal.source_message_id]))[-8:]
                    changed = True
                    logger.info("STM_ITEM_REINFORCED id=%s category=%s", item.id, item.category.value)
            for proposal in patch.add:
                if (source_by_id.get(proposal.source_message_id) != proposal.source.value
                    or proposal.source not in {Source.USER, Source.TOOL} or proposal.confidence < 0.7
                    or not _grounded(proposal.content, proposal.source, (evidence_by_id or {}).get(proposal.source_message_id, ""))):
                    continue
                match = next((item for item in items.values() if item.category == proposal.category and
                              SequenceMatcher(None, item.content, proposal.content).ratio() >= 0.94), None)
                if match:
                    if proposal.source_message_id not in match.source_message_ids:
                        match.last_seen_at = match.last_reinforced_at = now
                        match.reinforcements += 1
                        match.status = Status.ACTIVE
                        match.source_message_ids = list(dict.fromkeys([*match.source_message_ids, proposal.source_message_id]))[-8:]
                        logger.info("STM_ITEM_REINFORCED id=%s category=%s", match.id, match.category.value)
                    else:
                        continue
                else:
                    item = ShortTermMemoryItem(category=proposal.category, content=proposal.content.strip(),
                                               source=proposal.source, source_message_ids=[proposal.source_message_id],
                                               first_seen_at=now, last_seen_at=now, last_reinforced_at=now,
                                               confidence=proposal.confidence)
                    items[item.id] = item
                    logger.info("STM_ITEM_ADDED id=%s category=%s", item.id, item.category.value)
                changed = True
        # Semantic category determines decay speed; no fixed seven-day deletion.
        for item in list(items.values()):
            idle = now - item.last_reinforced_at
            if item.category == Category.RECENT_TOPIC and idle > timedelta(days=3) and item.status == Status.ACTIVE:
                item.status = Status.FADING
                changed = True
                logger.info("STM_ITEM_FADED id=%s category=%s", item.id, item.category.value)
            # Removal requires a semantic patch. Age alone never erases a context.
        bounded = []
        for category, limit in LIMITS.items():
            group = sorted((item for item in items.values() if item.category == category),
                           key=lambda item: (item.status == Status.ACTIVE, item.last_reinforced_at), reverse=True)
            bounded.extend(group[:limit])
        state.items = bounded
        # Overview is rendered from evidence, never freely rewritten by the model.
        contexts = [x.content for x in bounded if x.category in {Category.ACTIVE_CONTEXT, Category.ACTIVE_THREAD}
                    and x.status == Status.ACTIVE]
        state.overview = "；".join(contexts[:4]) + ("。" if contexts else "")
        state.last_processed_message_id = last_message_id
        if changed:
            state.version += 1
            state.updated_at = now
        self.last_maintenance = {"result": "UPDATE" if changed else "NO_CHANGE",
                                 "patch": patch.model_dump(mode="json"), "at": now.isoformat()}
        state.last_maintenance = self.last_maintenance
        self.store.save(state)
        logger.info("STM_PATCH_APPLIED count=%d version=%d", len(bounded), state.version) if changed else logger.info("STM_NO_CHANGE")
        return state

    def record_failure(self, exc: Exception) -> None:
        state = self.state()
        self.last_maintenance = {"result": "FAILED", "error_type": type(exc).__name__,
                                 "last_processed_message_id": state.last_processed_message_id}
        state.last_maintenance = self.last_maintenance
        self.store.save(state)
