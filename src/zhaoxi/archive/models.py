"""Public and internal data models for the Tidecourt Archive."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ArchiveScope(StrEnum):
    ZHAOXI = "zhaoxi"
    USER = "user"
    PROJECTS = "projects"
    REFERENCE = "reference"


class ArchiveAuthority(StrEnum):
    CANONICAL = "canonical"
    REFERENCE = "reference"
    PERSONAL = "personal"
    DRAFT = "draft"


class ArchiveAttachment(BaseModel):
    type: str = Field(min_length=1, max_length=40)
    path: str = Field(min_length=1, max_length=500)


class ParsedDocument(BaseModel):
    document_id: str
    title: str
    scope: ArchiveScope
    type: str
    authority: ArchiveAuthority
    updated_at: str
    tags: list[str] = Field(default_factory=list)
    attachments: list[ArchiveAttachment] = Field(default_factory=list)
    source_path: str
    content: str


class ArchiveChunk(BaseModel):
    heading_path: str
    content: str
    chunk_index: int


class IndexReport(BaseModel):
    documents: int
    chunks: int
    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0
    errors: list[dict[str, str]] = Field(default_factory=list)
    last_indexed_at: str


class DocumentSummary(BaseModel):
    document_id: str
    title: str
    scope: ArchiveScope
    type: str
    authority: ArchiveAuthority
    updated_at: str
    source_path: str
    tags: list[str] = Field(default_factory=list)
    attachments: list[ArchiveAttachment] = Field(default_factory=list)


class SearchResult(DocumentSummary):
    heading_path: str
    snippet: str
    score: float


class ReadResult(DocumentSummary):
    section: str | None = None
    content: str
    truncated: bool = False


def json_list(value: list[Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)
