"""Atomic local emoji library management."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from pathlib import Path
from threading import RLock

from pydantic import BaseModel, Field, ValidationError

from zhaoxi.expression.emoji_service import EmojiEntry, EmojiService, SUPPORTED_SUFFIXES

MAX_EMOJI_BYTES = 100 * 1024 * 1024
_DATA_URL = re.compile(r"^data:image/(png|jpeg|webp|gif);base64,([A-Za-z0-9+/=]+)$")
_MIME_SUFFIX = {"png": ".png", "jpeg": ".jpg", "webp": ".webp", "gif": ".gif"}


class EmojiMetadata(BaseModel):
    description: str = Field(min_length=2, max_length=2000)
    tags: list[str] = Field(min_length=1, max_length=50)
    emotion: str | None = Field(default=None, max_length=80)
    intensity: float | None = Field(default=None, ge=0, le=1)
    enabled: bool = True


class EmojiMutationResult(BaseModel):
    status: str
    emoji_id: str | None = None
    pending_id: str | None = None


def decode_image_data_url(value: str) -> tuple[bytes, str]:
    match = _DATA_URL.fullmatch(value)
    if not match:
        raise ValueError("仅支持 PNG、JPEG、WebP 或 GIF 图片")
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("图片 base64 数据无效") from exc
    if not raw or len(raw) > MAX_EMOJI_BYTES:
        raise ValueError("图片不能为空或超过 100 MB")
    kind = match.group(1)
    valid = (
        kind == "png" and raw.startswith(b"\x89PNG\r\n\x1a\n")
        or kind == "jpeg" and raw.startswith(b"\xff\xd8\xff")
        or kind == "webp" and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
        or kind == "gif" and raw[:6] in {b"GIF87a", b"GIF89a"}
    )
    if not valid:
        raise ValueError("图片内容与格式不匹配")
    return raw, _MIME_SUFFIX[kind]


class EmojiManager:
    """Own every file and registry mutation for one EmojiService."""

    def __init__(self, service: EmojiService) -> None:
        self.service = service
        self.registry_path = service.registry_path
        self.root = self.registry_path.parent
        self.images_dir = self.root / "images"
        self.pending_dir = self.root / "pending"
        self._lock = RLock()
        self.last_added: str | None = None
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        if not self.registry_path.exists():
            self._write_registry([])

    def _records(self) -> list[EmojiEntry]:
        try:
            raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise ValueError("registry root must be a list")
            return [EmojiEntry.model_validate(item) for item in raw]
        except (OSError, json.JSONDecodeError, ValidationError, ValueError, TypeError) as exc:
            raise ValueError("表情注册表无效") from exc

    def _write_registry(self, records: list[EmojiEntry]) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.registry_path.with_suffix(self.registry_path.suffix + ".tmp")
        payload = json.dumps([item.model_dump(mode="json") for item in records], ensure_ascii=False, indent=2)
        temporary.write_text(payload, encoding="utf-8")
        json.loads(temporary.read_text(encoding="utf-8"))
        temporary.replace(self.registry_path)

    @staticmethod
    def _next_id(prefix: str, existing: set[str]) -> str:
        number = 1
        while f"{prefix}_{number:04d}" in existing:
            number += 1
        return f"{prefix}_{number:04d}"

    @staticmethod
    def _digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _duplicate(self, raw: bytes, records: list[EmojiEntry]) -> str | None:
        wanted = hashlib.sha256(raw).hexdigest()
        for item in records:
            path = (self.root / item.file).resolve()
            if path.is_file() and self._digest(path) == wanted:
                return item.id
        return None

    def list_all(self, query: str = "", enabled: bool | None = None) -> list[dict]:
        needle = query.casefold().strip()
        values = []
        for item in reversed(self._records()):
            if enabled is not None and item.enabled != enabled:
                continue
            haystack = " ".join((item.id, item.description, item.emotion or "", *item.tags)).casefold()
            if needle and needle not in haystack:
                continue
            values.append({**item.model_dump(mode="json"), "url": f"/api/expression/emoji/{item.id}"})
        return values

    def get(self, emoji_id: str) -> EmojiEntry | None:
        return next((item for item in self._records() if item.id == emoji_id), None)

    def image_path(self, emoji_id: str) -> Path | None:
        item = self.get(emoji_id)
        if item is None:
            return None
        path = (self.root / item.file).resolve()
        try:
            path.relative_to(self.images_dir.resolve())
        except ValueError:
            return None
        return path if path.is_file() else None

    def add_data_url(self, data_url: str, metadata: EmojiMetadata) -> EmojiMutationResult:
        raw, suffix = decode_image_data_url(data_url)
        with self._lock:
            records = self._records()
            if duplicate := self._duplicate(raw, records):
                return EmojiMutationResult(status="duplicate", emoji_id=duplicate)
            emoji_id = self._next_id("emoji", {item.id for item in records})
            destination = self.images_dir / f"{emoji_id}{suffix}"
            destination.write_bytes(raw)
            record = EmojiEntry(id=emoji_id, file=f"images/{destination.name}", **metadata.model_dump())
            try:
                self._write_registry([*records, record])
            except Exception:
                destination.unlink(missing_ok=True)
                raise
            self.service.reload()
            self.last_added = emoji_id
            return EmojiMutationResult(status="added", emoji_id=emoji_id)

    def update_metadata(self, emoji_id: str, metadata: EmojiMetadata) -> EmojiMutationResult:
        with self._lock:
            records = self._records()
            index = next((i for i, item in enumerate(records) if item.id == emoji_id), None)
            if index is None:
                return EmojiMutationResult(status="not_found")
            records[index] = records[index].model_copy(update=metadata.model_dump())
            self._write_registry(records)
            self.service.reload()
            return EmojiMutationResult(status="updated", emoji_id=emoji_id)

    def delete(self, emoji_id: str) -> EmojiMutationResult:
        with self._lock:
            records = self._records()
            item = next((entry for entry in records if entry.id == emoji_id), None)
            if item is None:
                return EmojiMutationResult(status="not_found")
            source = (self.root / item.file).resolve()
            backup = source.with_suffix(source.suffix + ".deleting")
            if source.exists():
                source.replace(backup)
            try:
                self._write_registry([entry for entry in records if entry.id != emoji_id])
            except Exception:
                if backup.exists():
                    backup.replace(source)
                raise
            backup.unlink(missing_ok=True)
            self.service.reload()
            return EmojiMutationResult(status="deleted", emoji_id=emoji_id)

    def add_pending(self, data_url: str) -> EmojiMutationResult:
        raw, suffix = decode_image_data_url(data_url)
        with self._lock:
            if duplicate := self._duplicate(raw, self._records()):
                return EmojiMutationResult(status="duplicate", emoji_id=duplicate)
            for path in self.pending_dir.iterdir():
                if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES and self._digest(path) == hashlib.sha256(raw).hexdigest():
                    return EmojiMutationResult(status="duplicate_pending", pending_id=path.stem)
            pending_id = self._next_id("pending", {path.stem for path in self.pending_dir.iterdir()})
            (self.pending_dir / f"{pending_id}{suffix}").write_bytes(raw)
            return EmojiMutationResult(status="pending", pending_id=pending_id)

    def list_pending(self) -> list[dict]:
        return [
            {"pending_id": path.stem, "url": f"/api/emoji/pending/{path.stem}/image"}
            for path in sorted(self.pending_dir.iterdir(), reverse=True)
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
        ]

    def pending_path(self, pending_id: str) -> Path | None:
        if not re.fullmatch(r"pending_\d{4}", pending_id):
            return None
        path = next((item for item in self.pending_dir.glob(f"{pending_id}.*") if item.suffix.lower() in SUPPORTED_SUFFIXES), None)
        return path if path and path.is_file() else None

    def delete_pending(self, pending_id: str) -> EmojiMutationResult:
        path = self.pending_path(pending_id)
        if path is None:
            return EmojiMutationResult(status="not_found")
        path.unlink()
        return EmojiMutationResult(status="deleted", pending_id=pending_id)

    def commit_pending(self, pending_id: str, metadata: EmojiMetadata) -> EmojiMutationResult:
        path = self.pending_path(pending_id)
        if path is None:
            return EmojiMutationResult(status="not_found")
        kind = "jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else path.suffix.lower().lstrip(".")
        data_url = f"data:image/{kind};base64,{base64.b64encode(path.read_bytes()).decode()}"
        result = self.add_data_url(data_url, metadata)
        if result.status in {"added", "duplicate"}:
            path.unlink(missing_ok=True)
        return result

    def diagnostics(self) -> dict:
        return {
            "pending_emojis": len(self.list_pending()),
            "last_added": self.last_added,
            "registry_status": "ok" if self.registry_path.is_file() else "missing",
        }
