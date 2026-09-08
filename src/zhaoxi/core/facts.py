"""Provenance and domain-authority policy for facts from memory and tools."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class FactDomain(StrEnum):
    STRUCTURED_LIFE = "structured_life"
    EXPERIENCE = "experience"
    CANONICAL = "canonical"
    GENERAL = "general"


class FactSourceKind(StrEnum):
    USER = "user"
    ARCHIVE = "archive"
    MEMORY = "memory"
    STRUCTURED_TOOL = "structured_tool"
    GENERAL = "general"


class FactObservation(BaseModel):
    value: Any
    source: str
    source_kind: FactSourceKind = FactSourceKind.GENERAL
    domain: FactDomain
    observed_at: datetime
    valid_at: datetime | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)
    authority: int = Field(default=0, ge=0, le=100)
    external_ref: str | None = None

    @model_validator(mode="after")
    def normalize_times(self) -> "FactObservation":
        if self.observed_at.tzinfo is None or (self.valid_at and self.valid_at.tzinfo is None):
            raise ValueError("fact provenance timestamps must include a timezone")
        self.observed_at = self.observed_at.astimezone(UTC)
        if self.valid_at:
            self.valid_at = self.valid_at.astimezone(UTC)
        return self


class DomainAuthorityPolicy:
    """Choose a fact for the question's domain without deleting other sources."""

    SOURCE_RANKS = {
        FactDomain.STRUCTURED_LIFE: {FactSourceKind.STRUCTURED_TOOL: 30, FactSourceKind.MEMORY: 20},
        FactDomain.EXPERIENCE: {FactSourceKind.MEMORY: 30, FactSourceKind.STRUCTURED_TOOL: 20},
        FactDomain.CANONICAL: {FactSourceKind.USER: 40, FactSourceKind.ARCHIVE: 30, FactSourceKind.MEMORY: 20},
        FactDomain.GENERAL: {},
    }

    def resolve(self, observations: list[FactObservation], domain: FactDomain) -> FactObservation | None:
        candidates = [item for item in observations if item.domain == domain]
        ranks = self.SOURCE_RANKS[domain]
        return max(
            candidates,
            key=lambda item: (
                ranks.get(item.source_kind, 10),
                item.authority,
                item.confidence,
                item.valid_at or item.observed_at,
            ),
            default=None,
        )
