"""Safe Markdown/front-matter parsing and heading-aware chunking."""

from __future__ import annotations

from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
import re
from typing import Any

import yaml

from zhaoxi.archive.models import (
    ArchiveAttachment,
    ArchiveAuthority,
    ArchiveChunk,
    ArchiveScope,
    ParsedDocument,
)


class ArchiveParseError(ValueError):
    """One document is invalid; indexing may continue with other documents."""


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_ID = re.compile(r"^[\w.-]{1,160}$", re.UNICODE)


def _default_id(relative_path: str) -> str:
    stem = re.sub(r"[^\w.-]+", "-", PurePosixPath(relative_path).stem, flags=re.UNICODE).strip("-.")
    digest = sha256(relative_path.casefold().encode("utf-8")).hexdigest()[:12]
    return f"{stem or 'document'}-{digest}"


def _front_matter(text: str) -> tuple[dict[str, Any], str]:
    normalized = text.lstrip("\ufeff")
    if not normalized.startswith("---\n") and not normalized.startswith("---\r\n"):
        return {}, normalized
    lines = normalized.splitlines(keepends=True)
    end = next((index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
    if end is None:
        raise ArchiveParseError("front matter 缺少结束分隔符 ---")
    try:
        metadata = yaml.safe_load("".join(lines[1:end])) or {}
    except yaml.YAMLError as exc:
        raise ArchiveParseError(f"front matter YAML 无效：{exc}") from exc
    if not isinstance(metadata, dict):
        raise ArchiveParseError("front matter 必须是 YAML object")
    return metadata, "".join(lines[end + 1 :]).lstrip("\r\n")


def _string(metadata: dict[str, Any], key: str, default: str) -> str:
    value = metadata.get(key, default)
    if value is None:
        return default
    if not isinstance(value, (str, int, float, date)):
        raise ArchiveParseError(f"front matter 字段 {key} 必须是字符串")
    result = str(value).strip()
    return result or default


def parse_document(
    text: str,
    *,
    relative_path: str,
    modified_at: float,
    archive_root: Path,
) -> ParsedDocument:
    metadata, body = _front_matter(text)
    path = PurePosixPath(relative_path)
    default_scope = path.parts[0] if path.parts and path.parts[0] in {item.value for item in ArchiveScope} else "reference"
    document_id = _string(metadata, "id", _default_id(relative_path))
    if not _ID.fullmatch(document_id):
        raise ArchiveParseError("front matter 字段 id 只能包含字母、数字、下划线、点和连字符")
    first_heading = next(
        (match.group(2).strip() for line in body.splitlines() if (match := _HEADING.match(line))),
        path.stem,
    )
    try:
        scope = ArchiveScope(_string(metadata, "scope", default_scope))
    except ValueError as exc:
        raise ArchiveParseError("scope 必须是 zhaoxi、user、projects 或 reference") from exc
    default_authority = "personal" if scope is ArchiveScope.USER else "reference"
    try:
        authority = ArchiveAuthority(_string(metadata, "authority", default_authority))
    except ValueError as exc:
        raise ArchiveParseError("authority 必须是 canonical、reference、personal 或 draft") from exc
    tags_value = metadata.get("tags", [])
    if isinstance(tags_value, str):
        tags = [tags_value.strip()] if tags_value.strip() else []
    elif isinstance(tags_value, list) and all(isinstance(item, (str, int, float)) for item in tags_value):
        tags = [str(item).strip() for item in tags_value if str(item).strip()]
    else:
        raise ArchiveParseError("front matter 字段 tags 必须是字符串列表")
    attachments_value = metadata.get("attachments", [])
    if attachments_value is None:
        attachments_value = []
    if not isinstance(attachments_value, list):
        raise ArchiveParseError("front matter 字段 attachments 必须是列表")
    attachments: list[ArchiveAttachment] = []
    root = archive_root.resolve()
    source_parent = (root / path).parent
    for raw in attachments_value:
        if not isinstance(raw, dict):
            raise ArchiveParseError("attachment 必须包含 type 与 path")
        try:
            attachment = ArchiveAttachment.model_validate(raw)
        except Exception as exc:
            raise ArchiveParseError(f"attachment 无效：{exc}") from exc
        attachment_path = Path(attachment.path)
        if attachment_path.is_absolute():
            raise ArchiveParseError("attachment path 不允许使用绝对路径")
        resolved = (source_parent / attachment_path).resolve()
        if not resolved.is_relative_to(root):
            raise ArchiveParseError("attachment path 不允许逃逸 archive 目录")
        attachments.append(attachment.model_copy(update={"path": resolved.relative_to(root).as_posix()}))
    updated_at = _string(
        metadata,
        "updated_at",
        datetime.fromtimestamp(modified_at, UTC).date().isoformat(),
    )
    return ParsedDocument(
        document_id=document_id,
        title=_string(metadata, "title", first_heading),
        scope=scope,
        type=_string(metadata, "type", "document"),
        authority=authority,
        updated_at=updated_at,
        tags=tags,
        attachments=attachments,
        source_path=relative_path,
        content=body,
    )


def chunk_markdown(text: str, *, max_chars: int = 3000, overlap: int = 200) -> list[ArchiveChunk]:
    """Split at Markdown headings, then bound unusually long sections."""
    headings: list[str] = []
    sections: list[tuple[str, str]] = []
    current_heading = "文档开头"
    current: list[str] = []
    for line in text.splitlines():
        match = _HEADING.match(line)
        if match:
            if any(part.strip() for part in current):
                sections.append((current_heading, "\n".join(current).strip()))
            level = len(match.group(1))
            title = match.group(2).strip()
            headings[:] = headings[: level - 1]
            headings.append(title)
            current_heading = " > ".join(headings)
            current = [line]
        else:
            current.append(line)
    if any(part.strip() for part in current):
        sections.append((current_heading, "\n".join(current).strip()))
    if not sections and text.strip():
        sections = [("文档开头", text.strip())]

    chunks: list[ArchiveChunk] = []
    step = max(1, max_chars - overlap)
    for heading_path, content in sections:
        start = 0
        while start < len(content):
            end = min(len(content), start + max_chars)
            if end < len(content):
                boundary = content.rfind("\n", start + max_chars // 2, end)
                if boundary > start:
                    end = boundary
            piece = content[start:end].strip()
            if piece:
                chunks.append(ArchiveChunk(
                    heading_path=heading_path,
                    content=piece,
                    chunk_index=len(chunks),
                ))
            if end >= len(content):
                break
            start = max(start + 1, end - overlap)
    return chunks
