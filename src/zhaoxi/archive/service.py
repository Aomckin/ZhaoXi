"""SQLite-backed indexing and retrieval for the Tidecourt Archive."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import sqlite3
from typing import Iterable

from zhaoxi.archive.models import (
    ArchiveAttachment,
    ArchiveAuthority,
    ArchiveScope,
    DocumentSummary,
    IndexReport,
    ReadResult,
    SearchResult,
    json_list,
)
from zhaoxi.archive.parser import ArchiveParseError, chunk_markdown, parse_document


class ArchiveNotFoundError(LookupError):
    pass


class ArchiveSecurityError(ValueError):
    pass


class ArchiveService:
    """Treat Markdown as source of truth and SQLite as a disposable local index."""

    def __init__(
        self,
        archive_directory: str | Path,
        db_path: str | Path,
        *,
        search_top_k: int = 5,
        context_max_chars: int = 6000,
        max_document_chars: int = 12_000,
        chunk_max_chars: int = 3000,
        chunk_overlap_chars: int = 200,
    ) -> None:
        self.archive_directory = Path(archive_directory).expanduser().resolve()
        self.db_path = Path(db_path).expanduser().resolve()
        self.search_top_k = search_top_k
        self.context_max_chars = context_max_chars
        self.max_document_chars = max_document_chars
        self.chunk_max_chars = chunk_max_chars
        self.chunk_overlap_chars = chunk_overlap_chars
        self.archive_directory.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    type TEXT NOT NULL,
                    authority TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    attachments_json TEXT NOT NULL,
                    source_path TEXT NOT NULL UNIQUE,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
                    chunk_index INTEGER NOT NULL,
                    heading_path TEXT NOT NULL,
                    content TEXT NOT NULL,
                    UNIQUE(document_id, chunk_index)
                );
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS index_state (
                    source_path TEXT PRIMARY KEY,
                    document_id TEXT,
                    content_hash TEXT,
                    status TEXT NOT NULL,
                    error TEXT,
                    indexed_at TEXT NOT NULL
                );
                """
            )
            try:
                connection.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5("
                    "title, heading_path, tags, content, tokenize='trigram')"
                )
                tokenizer = "trigram"
            except sqlite3.OperationalError:
                connection.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5("
                    "title, heading_path, tags, content, tokenize='unicode61')"
                )
                tokenizer = "unicode61"
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('fts_tokenizer', ?)",
                (tokenizer,),
            )

    def _delete_document(self, connection: sqlite3.Connection, document_id: str) -> None:
        chunk_ids = [
            row["chunk_id"]
            for row in connection.execute(
                "SELECT chunk_id FROM chunks WHERE document_id=?", (document_id,)
            )
        ]
        connection.executemany("DELETE FROM chunks_fts WHERE rowid=?", ((item,) for item in chunk_ids))
        connection.execute("DELETE FROM documents WHERE document_id=?", (document_id,))

    def _safe_files(self) -> tuple[list[tuple[Path, str]], list[dict[str, str]]]:
        files: list[tuple[Path, str]] = []
        errors: list[dict[str, str]] = []
        root = self.archive_directory
        for candidate in sorted(root.rglob("*.md")):
            relative = candidate.relative_to(root).as_posix()
            try:
                resolved = candidate.resolve(strict=True)
                if candidate.is_symlink() or not resolved.is_relative_to(root):
                    raise ArchiveSecurityError("符号链接或路径指向 archive 目录之外")
                if not resolved.is_file():
                    continue
            except (OSError, ArchiveSecurityError) as exc:
                errors.append({"source_path": relative, "error": str(exc)})
                continue
            files.append((resolved, relative))
        return files, errors

    def reindex(self, *, force: bool = False) -> IndexReport:
        """Incrementally synchronize the SQLite index with current Markdown files."""
        now = datetime.now(UTC).isoformat()
        files, errors = self._safe_files()
        seen_paths = {relative for _, relative in files}
        added = updated = removed = unchanged = 0
        with self._connect() as connection:
            existing_by_path = {
                row["source_path"]: dict(row)
                for row in connection.execute(
                    "SELECT document_id, source_path, content_hash FROM documents"
                )
            }
            if force:
                connection.execute("DELETE FROM chunks_fts")
                connection.execute("DELETE FROM chunks")
                connection.execute("DELETE FROM documents")
                connection.execute("DELETE FROM index_state")
                existing_by_path = {}
            for path, relative in files:
                raw = path.read_bytes()
                content_hash = sha256(raw).hexdigest()
                previous = existing_by_path.get(relative)
                if previous and previous["content_hash"] == content_hash:
                    unchanged += 1
                    connection.execute(
                        "INSERT OR REPLACE INTO index_state VALUES(?, ?, ?, 'ok', NULL, ?)",
                        (relative, previous["document_id"], content_hash, now),
                    )
                    continue
                try:
                    text = raw.decode("utf-8")
                    document = parse_document(
                        text,
                        relative_path=relative,
                        modified_at=path.stat().st_mtime,
                        archive_root=self.archive_directory,
                    )
                    owner = connection.execute(
                        "SELECT source_path FROM documents WHERE document_id=?",
                        (document.document_id,),
                    ).fetchone()
                    if owner is not None and owner["source_path"] != relative:
                        raise ArchiveParseError(
                            f"document id {document.document_id!r} 已由 {owner['source_path']} 使用"
                        )
                    if previous:
                        self._delete_document(connection, previous["document_id"])
                    chunks = chunk_markdown(
                        document.content,
                        max_chars=self.chunk_max_chars,
                        overlap=self.chunk_overlap_chars,
                    )
                    connection.execute(
                        """INSERT INTO documents VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            document.document_id,
                            document.title,
                            document.scope.value,
                            document.type,
                            document.authority.value,
                            document.updated_at,
                            json_list(document.tags),
                            json_list([item.model_dump() for item in document.attachments]),
                            relative,
                            document.content,
                            content_hash,
                        ),
                    )
                    for chunk in chunks:
                        cursor = connection.execute(
                            "INSERT INTO chunks(document_id, chunk_index, heading_path, content) VALUES(?, ?, ?, ?)",
                            (document.document_id, chunk.chunk_index, chunk.heading_path, chunk.content),
                        )
                        connection.execute(
                            "INSERT INTO chunks_fts(rowid, title, heading_path, tags, content) VALUES(?, ?, ?, ?, ?)",
                            (cursor.lastrowid, document.title, chunk.heading_path, " ".join(document.tags), chunk.content),
                        )
                    connection.execute(
                        "INSERT OR REPLACE INTO index_state VALUES(?, ?, ?, 'ok', NULL, ?)",
                        (relative, document.document_id, content_hash, now),
                    )
                    if previous:
                        updated += 1
                    else:
                        added += 1
                except (UnicodeDecodeError, OSError, ArchiveParseError) as exc:
                    if previous:
                        self._delete_document(connection, previous["document_id"])
                    message = str(exc)
                    errors.append({"source_path": relative, "error": message})
                    connection.execute(
                        "INSERT OR REPLACE INTO index_state VALUES(?, NULL, ?, 'error', ?, ?)",
                        (relative, content_hash, message[:1000], now),
                    )
            for source_path, previous in existing_by_path.items():
                if source_path not in seen_paths:
                    self._delete_document(connection, previous["document_id"])
                    connection.execute("DELETE FROM index_state WHERE source_path=?", (source_path,))
                    removed += 1
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('last_indexed_at', ?)",
                (now,),
            )
        status = self.status()
        return IndexReport(
            documents=status["documents"],
            chunks=status["chunks"],
            added=added,
            updated=updated,
            removed=removed,
            unchanged=unchanged,
            errors=errors,
            last_indexed_at=now,
        )

    @staticmethod
    def _summary(row: sqlite3.Row) -> DocumentSummary:
        return DocumentSummary(
            document_id=row["document_id"],
            title=row["title"],
            scope=ArchiveScope(row["scope"]),
            type=row["type"],
            authority=ArchiveAuthority(row["authority"]),
            updated_at=row["updated_at"],
            source_path=row["source_path"],
            tags=json.loads(row["tags_json"]),
            attachments=[ArchiveAttachment.model_validate(item) for item in json.loads(row["attachments_json"])],
        )

    def list_documents(
        self,
        *,
        scope: ArchiveScope | None = None,
        type: str | None = None,
        authority: ArchiveAuthority | None = None,
        limit: int = 50,
    ) -> list[DocumentSummary]:
        clauses: list[str] = []
        values: list[object] = []
        for column, value in (("scope", scope), ("type", type), ("authority", authority)):
            if value is not None:
                clauses.append(f"{column}=?")
                values.append(value.value if isinstance(value, StrEnum) else value)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM documents{where} ORDER BY updated_at DESC, title LIMIT ?",
                (*values, limit),
            ).fetchall()
        return [self._summary(row) for row in rows]

    @staticmethod
    def _terms(query: str) -> list[str]:
        normalized = query.casefold()
        for stop in ("为什么", "是什么", "哪一天", "什么时候", "请问", "具体", "最近", "关于"):
            normalized = normalized.replace(stop, " ")
        words = re.findall(r"[a-z0-9_.-]{2,}|[\u3400-\u9fff]+", normalized)
        terms: list[str] = []
        for word in words:
            if re.fullmatch(r"[\u3400-\u9fff]+", word):
                if len(word) <= 3:
                    terms.append(word)
                else:
                    terms.append(word)
                    terms.extend(word[index : index + 2] for index in range(len(word) - 1))
            else:
                terms.append(word)
        return list(dict.fromkeys(term for term in terms if term.strip()))

    @staticmethod
    def _text_score(query: str, terms: Iterable[str], *, title: str, heading: str, tags: str, content: str) -> float:
        fields = [title.casefold(), heading.casefold(), tags.casefold(), content.casefold()]
        query = query.casefold().strip()
        score = 0.0
        weights = (5.0, 4.0, 3.0, 1.0)
        if query:
            score += sum(weight * 5 for field, weight in zip(fields, weights) if query in field)
        for term in terms:
            score += sum(weight * min(field.count(term), 3) for field, weight in zip(fields, weights))
        return score

    @staticmethod
    def _snippet(content: str, terms: list[str], max_chars: int) -> str:
        if len(content) <= max_chars:
            return content
        folded = content.casefold()
        positions = [folded.find(term) for term in terms if folded.find(term) >= 0]
        center = min(positions) if positions else 0
        start = max(0, center - max_chars // 3)
        end = min(len(content), start + max_chars)
        prefix = "…" if start else ""
        suffix = "…" if end < len(content) else ""
        return prefix + content[start:end].strip() + suffix

    def search(
        self,
        query: str,
        *,
        scope: ArchiveScope | None = None,
        type: str | None = None,
        authority: ArchiveAuthority | None = None,
        top_k: int | None = None,
        max_chars: int | None = None,
    ) -> list[SearchResult]:
        query = query.strip()
        if not query:
            return []
        limit = min(top_k or self.search_top_k, self.search_top_k)
        budget = min(max_chars or self.context_max_chars, self.context_max_chars)
        clauses: list[str] = []
        values: list[object] = []
        for column, value in (("d.scope", scope), ("d.type", type), ("d.authority", authority)):
            if value is not None:
                clauses.append(f"{column}=?")
                values.append(value.value if isinstance(value, StrEnum) else value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"""SELECT d.*, c.chunk_id, c.heading_path, c.content AS chunk_content
                    FROM chunks c JOIN documents d ON d.document_id=c.document_id
                    {where}""",
                values,
            ).fetchall()
            fts_scores: dict[int, float] = {}
            fts_terms = [term for term in self._terms(query) if len(term) >= 3]
            if fts_terms:
                expression = " OR ".join('"' + term.replace('"', '""') + '"' for term in fts_terms)
                try:
                    fts_scores = {
                        row["rowid"]: max(0.0, -float(row["rank"]))
                        for row in connection.execute(
                            "SELECT rowid, bm25(chunks_fts, 5.0, 4.0, 3.0, 1.0) AS rank "
                            "FROM chunks_fts WHERE chunks_fts MATCH ?",
                            (expression,),
                        )
                    }
                except sqlite3.OperationalError:
                    fts_scores = {}
        terms = self._terms(query)
        ranked: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            score = self._text_score(
                query,
                terms,
                title=row["title"],
                heading=row["heading_path"],
                tags=" ".join(json.loads(row["tags_json"])),
                content=row["chunk_content"],
            )
            if score <= 0:
                continue
            authority_boost = {
                "canonical": 1.15,
                "reference": 1.05,
                "personal": 1.03,
                "draft": 0.92,
            }[row["authority"]]
            # FTS5/BM25 narrows strong phrase matches; deterministic field scoring
            # remains the Chinese substring fallback for short two-character terms.
            score += min(fts_scores.get(row["chunk_id"], 0.0), 20.0)
            ranked.append((score * authority_boost, row))
        ranked.sort(key=lambda item: (-item[0], item[1]["title"], item[1]["heading_path"]))
        results: list[SearchResult] = []
        remaining = budget
        for score, row in ranked:
            if len(results) >= limit or remaining <= 0:
                break
            snippet = self._snippet(row["chunk_content"], terms, min(800, remaining))
            snippet = snippet[:remaining]
            if not snippet:
                continue
            summary = self._summary(row)
            results.append(SearchResult(
                **summary.model_dump(),
                heading_path=row["heading_path"],
                snippet=snippet,
                score=round(1 - math.exp(-score / 20), 4),
            ))
            remaining -= len(snippet)
        return results

    def read_document(
        self,
        document_id: str,
        *,
        section: str | None = None,
        max_chars: int | None = None,
    ) -> ReadResult:
        limit = min(max_chars or self.max_document_chars, self.max_document_chars)
        with self._connect() as connection:
            document = connection.execute(
                "SELECT * FROM documents WHERE document_id=?", (document_id,)
            ).fetchone()
            if document is None:
                raise ArchiveNotFoundError(f"书库中不存在文档：{document_id}")
            if section:
                chunks = connection.execute(
                    "SELECT heading_path, content FROM chunks WHERE document_id=? ORDER BY chunk_index",
                    (document_id,),
                ).fetchall()
                selected = [row["content"] for row in chunks if section.casefold() in row["heading_path"].casefold()]
                if not selected:
                    raise ArchiveNotFoundError(f"文档 {document_id} 中不存在章节：{section}")
                content = "\n\n".join(selected)
            else:
                content = document["content"]
        truncated = len(content) > limit
        content = content[: max(0, limit - 1)] + ("…" if truncated else "")
        return ReadResult(
            **self._summary(document).model_dump(),
            section=section,
            content=content,
            truncated=truncated,
        )

    def status(self) -> dict[str, object]:
        with self._connect() as connection:
            documents = connection.execute("SELECT count(*) FROM documents").fetchone()[0]
            chunks = connection.execute("SELECT count(*) FROM chunks").fetchone()[0]
            errors = [
                {"source_path": row["source_path"], "error": row["error"]}
                for row in connection.execute(
                    "SELECT source_path, error FROM index_state WHERE status='error' ORDER BY source_path"
                )
            ]
            values = dict(connection.execute("SELECT key, value FROM metadata"))
        return {
            "enabled": True,
            "documents": documents,
            "chunks": chunks,
            "last_indexed_at": values.get("last_indexed_at"),
            "index_healthy": not errors,
            "index_errors": errors,
            "db_path": str(self.db_path),
            "directory": str(self.archive_directory),
            "fts_tokenizer": values.get("fts_tokenizer"),
        }
