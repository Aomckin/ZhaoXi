"""Provider-independent associative long-term memory models."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def aware_utc(value: datetime) -> datetime:
    """Legacy timezone-less Memory timestamps use the store's UTC convention."""
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).astimezone(timezone.utc)


class MemoryTimeModel(BaseModel):
    @field_validator('*', mode='after')
    @classmethod
    def normalize_datetimes(cls, value):
        return aware_utc(value) if isinstance(value, datetime) else value


class MemoryKind(StrEnum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    STATE = "state"
    INTENT = "intent"
    RELATIONSHIP = "relationship"


class MemoryShape(StrEnum):
    NODE = "node"
    EDGE = "edge"


class MemorySourceType(StrEnum):
    USER = "user"
    CONVERSATION = "conversation"
    TOOL = "tool"
    SYSTEM = "system"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    COLD = "cold"
    DORMANT = "dormant"
    ARCHIVED = "archived"
    SUPERSEDED = "superseded"
    FORGOTTEN = "forgotten"


class MemoryRelation(StrEnum):
    RELATED_TO = "related_to"
    PART_OF = "part_of"
    ABOUT = "about"
    MENTIONS = "mentions"
    HAPPENED_DURING = "happened_during"
    BEFORE = "before"
    AFTER = "after"
    EVIDENCE_FOR = "evidence_for"
    DERIVED_FROM = "derived_from"
    SUPERSEDES = "supersedes"
    CONTRADICTS = "contradicts"
    ASSOCIATED_WITH = "associated_with"


def _normalized_list(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized.lower() if normalized.isascii() else normalized)
    return result


class MemoryCreate(MemoryTimeModel):
    content: str = Field(min_length=1, max_length=20_000)
    kind: MemoryKind = MemoryKind.SEMANTIC
    shape: MemoryShape = MemoryShape.NODE
    summary: str | None = Field(default=None, max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=30)
    entities: list[str] = Field(default_factory=list, max_length=50)
    participants: list[str] = Field(default_factory=list, max_length=30)
    source_type: MemorySourceType = MemorySourceType.USER
    source_ref: str | None = Field(default=None, max_length=500)
    confidence: float = Field(default=1.0, ge=0, le=1)
    importance: float = Field(default=0.6, ge=0, le=1)
    activation: float | None = Field(default=None, ge=0, le=1)
    relevance: float | None = Field(default=0.7, ge=0, le=1, exclude=True)
    pinned: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    supersedes_id: str | None = None
    source_message_id: str | None = Field(default=None, max_length=500)
    source_message_ids: list[str] = Field(default_factory=list, max_length=100)
    source_name: str | None = Field(default=None, max_length=100)
    evidence_reference: str | None = Field(default=None, max_length=1000)
    evidence_memory_ids: list[str] = Field(default_factory=list, max_length=200)
    source_requeryable: bool = False
    event_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    last_confirmed_at: datetime | None = None
    derived_at: datetime | None = None

    @model_validator(mode="after")
    def initialize_activation(self) -> "MemoryCreate":
        if self.activation is None:
            self.activation = self.relevance if self.relevance is not None else 0.7
        return self

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("memory content cannot be blank")
        return value

    @field_validator("tags", "entities", "participants", "source_message_ids")
    @classmethod
    def normalize_lists(cls, values: list[str]) -> list[str]:
        return _normalized_list(values)


class MemoryCandidate(MemoryCreate):
    """One atomic fact extracted from a completed turn."""

    confidence: float = Field(default=0.85, ge=0, le=1)
    importance: float = Field(default=0.45, ge=0, le=1)
    activation: float | None = Field(default=0.75, ge=0, le=1)
    relevance: float | None = Field(default=None, exclude=True)
    relation: str | None = Field(default=None, max_length=100)
    relation_label: str | None = Field(default=None, max_length=100)
    source_entity: str | None = Field(default=None, max_length=200)
    target_entity: str | None = Field(default=None, max_length=200)
    # Internal compatibility only. AutoMemory must use entity names, not IDs.
    source_node_id: str | None = None
    target_node_id: str | None = None


class MemoryCandidateBatch(MemoryTimeModel):
    candidates: list[MemoryCandidate] = Field(default_factory=list, max_length=20)
    reason: str = ""


class MemoryUpdate(MemoryTimeModel):
    content: str | None = Field(default=None, min_length=1, max_length=20_000)
    kind: MemoryKind | None = None
    shape: MemoryShape | None = None
    summary: str | None = Field(default=None, max_length=500)
    tags: list[str] | None = Field(default=None, max_length=30)
    entities: list[str] | None = Field(default=None, max_length=50)
    participants: list[str] | None = Field(default=None, max_length=30)
    confidence: float | None = Field(default=None, ge=0, le=1)
    importance: float | None = Field(default=None, ge=0, le=1)
    activation: float | None = Field(default=None, ge=0, le=1)
    relevance: float | None = Field(default=None, ge=0, le=1, exclude=True)
    pinned: bool | None = None
    metadata: dict[str, Any] | None = None
    source_message_id: str | None = Field(default=None, max_length=500)
    source_message_ids: list[str] | None = Field(default=None, max_length=100)
    source_name: str | None = Field(default=None, max_length=100)
    evidence_reference: str | None = Field(default=None, max_length=1000)
    evidence_memory_ids: list[str] | None = Field(default=None, max_length=200)
    source_requeryable: bool | None = None
    event_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    last_confirmed_at: datetime | None = None

    @model_validator(mode="after")
    def migrate_relevance(self) -> "MemoryUpdate":
        if self.activation is None and self.relevance is not None:
            self.activation = self.relevance
        return self


class MemoryQuery(MemoryTimeModel):
    text: str = ""
    kind: MemoryKind | None = None
    tags: list[str] = Field(default_factory=list)
    source_type: MemorySourceType | None = None
    statuses: list[MemoryStatus] = Field(default_factory=lambda: [MemoryStatus.ACTIVE])
    limit: int = Field(default=10, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    per_cluster_limit: int = Field(default=2, ge=1, le=100)
    max_hops: int = Field(default=2, ge=0, le=2)
    min_edge_weight: float = Field(default=0.25, ge=0, le=1)
    explicit_recall: bool = False
    now: datetime | None = None


class MemoryRecord(MemoryTimeModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    kind: MemoryKind
    shape: MemoryShape = MemoryShape.NODE
    content: str
    normalized_content: str
    summary: str | None = None
    tags: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    participants: list[str] = Field(default_factory=list)
    source_type: MemorySourceType
    source_ref: str | None = None
    confidence: float
    importance: float = Field(default=0.6, ge=0, le=1)
    activation: float = Field(default=0.7, ge=0, le=1)
    pinned: bool = False
    status: MemoryStatus = MemoryStatus.ACTIVE
    supersedes_id: str | None = None
    cluster_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    event_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    last_confirmed_at: datetime | None = None
    derived_at: datetime | None = None
    accessed_at: datetime | None = None
    access_count: int = Field(default=0, ge=0)
    source_message_id: str | None = None
    source_message_ids: list[str] = Field(default_factory=list)
    source_name: str | None = None
    evidence_reference: str | None = None
    evidence_memory_ids: list[str] = Field(default_factory=list)
    source_requeryable: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def relevance(self) -> float:
        """Deprecated compatibility alias; contextual relevance is query-scoped."""
        return self.activation

    @relevance.setter
    def relevance(self, value: float) -> None:
        self.activation = value


class MemoryCluster(MemoryTimeModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    topic: str
    summary: str = ""
    importance: float = Field(default=0.5, ge=0, le=1)
    activation: float = Field(default=0.7, ge=0, le=1)
    time_start: datetime | None = None
    time_end: datetime | None = None
    member_count: int = 0
    representative_memory_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    centroid_embedding: list[float] = Field(default_factory=list)
    active: bool = True
    merged_into_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MemoryEdge(MemoryTimeModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    source_id: str
    target_id: str
    relation: MemoryRelation = MemoryRelation.RELATED_TO
    relation_label: str | None = None
    weight: float = Field(default=0.5, ge=0, le=1)
    confidence: float = Field(default=0.8, ge=0, le=1)
    activation: float = Field(default=0.5, ge=0, le=1)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    evidence_memory_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_activated_at: datetime | None = None


class MemoryEmbedding(MemoryTimeModel):
    memory_id: str
    embedding_model: str
    embedding_hash: str
    vector: list[float]
    updated_at: datetime = Field(default_factory=utc_now)


class MemoryEntity(MemoryTimeModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    canonical_name: str
    normalized_name: str
    aliases: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MemorySearchResult(MemoryTimeModel):
    record: MemoryRecord
    score: float = 0
    contextual_relevance: float = 0
    text_score: float = 0
    semantic_score: float = 0
    graph_score: float = 0
    time_score: float = 0
    activation_score: float = 0
    importance_score: float = 0
    cluster: MemoryCluster | None = None
    match_reason: str = ""
    why_selected: list[str] = Field(default_factory=list)
    seed_memory_id: str | None = None
    edge_relation: str | None = None
    relation_label: str | None = None
    graph_hop: int | None = None


class MemoryWriteResult(MemoryTimeModel):
    record: MemoryRecord
    created: bool
    duplicate: bool = False
    conflict_candidates: list[MemoryRecord] = Field(default_factory=list)
