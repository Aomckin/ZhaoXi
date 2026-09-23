"""Local, registry-backed emoji expression selection."""

from __future__ import annotations

import json
import logging
import random
import re
from collections import deque
from difflib import SequenceMatcher
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator

logger = logging.getLogger("EMOJI")
SUPPORTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


class EmojiEntry(BaseModel):
    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    file: str = Field(min_length=1, max_length=500)
    description: str = Field(min_length=1, max_length=2000)
    tags: list[str] = Field(min_length=1, max_length=50)
    emotion: str | None = Field(default=None, max_length=80)
    intensity: float | None = Field(default=None, ge=0, le=1)
    enabled: bool

    @field_validator("file")
    @classmethod
    def validate_relative_image(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise ValueError("表情文件必须是注册表目录内的受支持相对图片路径")
        return path.as_posix()


class EmojiCandidate(BaseModel):
    emoji_id: str
    path: str
    description: str
    emotion: str | None = None
    intensity: float | None = None
    score: float = Field(ge=0, le=1)


class EmojiResult(BaseModel):
    status: str
    emoji_id: str | None = None
    path: str | None = None
    score: float | None = None


def _terms(text: str) -> set[str]:
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text.casefold()).strip()
    values = {part for part in normalized.split() if part}
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
        values.update(run[index:index + size] for size in (2, 3, 4) for index in range(len(run) - size + 1))
    return values


class EmojiService:
    """Load, search and select local emoji without leaking file names to the LLM."""

    def __init__(
        self,
        registry_path: str | Path,
        *,
        enabled: bool = True,
        recent_history_size: int = 5,
        candidate_limit: int = 5,
        min_match_score: float = 0.4,
        random_source: random.Random | None = None,
    ) -> None:
        self.registry_path = Path(registry_path)
        self.enabled = enabled
        self.candidate_limit = candidate_limit
        self.min_match_score = min_match_score
        self.entries: list[EmojiEntry] = []
        self.recent_ids: deque[str] = deque(maxlen=recent_history_size)
        self.last_intent = ""
        self.last_requested_tags: list[str] = []
        self.last_candidates: list[EmojiCandidate] = []
        self.last_selected: str | None = None
        self.load_error: str | None = None
        self._random = random_source or random.Random()
        self.reload()

    def reload(self) -> int:
        self.entries = []
        self.load_error = None
        if not self.registry_path.is_file():
            self.load_error = "registry_missing"
            logger.warning("emoji registry missing path=%s", self.registry_path)
            return 0
        try:
            raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise ValueError("registry root must be a list")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.load_error = "registry_invalid"
            logger.warning("emoji registry unavailable type=%s", type(exc).__name__)
            return 0
        seen: set[str] = set()
        for record in raw:
            try:
                entry = EmojiEntry.model_validate(record)
                resolved = (self.registry_path.parent / entry.file).resolve()
                resolved.relative_to(self.registry_path.parent.resolve())
                if entry.id in seen or not resolved.is_file():
                    logger.warning("emoji entry skipped id=%s reason=%s", entry.id, "duplicate" if entry.id in seen else "missing_file")
                    continue
                if not entry.enabled:
                    continue
            except (ValidationError, ValueError, OSError, TypeError) as exc:
                logger.warning("emoji entry skipped type=%s", type(exc).__name__)
                continue
            seen.add(entry.id)
            self.entries.append(entry)
        return len(self.entries)

    def image_path(self, emoji_id: str) -> Path | None:
        entry = next((item for item in self.entries if item.id == emoji_id), None)
        if entry is None:
            return None
        path = (self.registry_path.parent / entry.file).resolve()
        try:
            path.relative_to(self.registry_path.parent.resolve())
        except ValueError:
            return None
        return path if path.is_file() else None

    def search(self, intent: str, emotion: str | None = None, intensity: float | None = None, limit: int | None = None) -> list[EmojiCandidate]:
        self.last_intent = intent.strip()
        if not self.enabled or not self.entries or not self.last_intent:
            self.last_candidates = []
            return []
        intent_terms = _terms(self.last_intent)
        candidates: list[EmojiCandidate] = []
        for entry in self.entries:
            document = " ".join((entry.description, *entry.tags, entry.emotion or ""))
            document_terms = _terms(document)
            overlap = len(intent_terms & document_terms) / max(1, min(len(intent_terms), len(document_terms)))
            tag_hit = max((1.0 if tag.casefold() in self.last_intent.casefold() else 0.0 for tag in entry.tags), default=0)
            similarity = SequenceMatcher(None, self.last_intent.casefold(), document.casefold()).ratio()
            score = max(overlap, tag_hit, similarity * 0.65)
            if emotion and entry.emotion and emotion.casefold() == entry.emotion.casefold():
                score += 0.25
            if intensity is not None and entry.intensity is not None:
                score += 0.1 * (1 - abs(intensity - entry.intensity))
            if entry.id in self.recent_ids:
                distance = list(reversed(self.recent_ids)).index(entry.id)
                score -= 0.3 if distance == 0 else max(0.08, 0.2 - distance * 0.04)
            score = min(1.0, max(0.0, score))
            if score >= self.min_match_score:
                candidates.append(EmojiCandidate(
                    emoji_id=entry.id,
                    path=str((self.registry_path.parent / entry.file).resolve()),
                    description=entry.description,
                    emotion=entry.emotion,
                    intensity=entry.intensity,
                    score=round(score, 4),
                ))
        candidates.sort(key=lambda item: (-item.score, item.emoji_id))
        self.last_candidates = candidates[: limit or self.candidate_limit]
        return list(self.last_candidates)

    def select(self, intent: str, emotion: str | None = None, intensity: float | None = None) -> EmojiResult:
        candidates = self.search(intent, emotion, intensity)
        if not candidates:
            self.last_selected = None
            return EmojiResult(status="no_match")
        best = candidates[0].score
        pool = [item for item in candidates if item.score >= max(self.min_match_score, best - 0.08)]
        if self.recent_ids and len(candidates) > 1:
            without_last = [item for item in pool if item.emoji_id != self.recent_ids[-1]]
            if not without_last:
                without_last = [item for item in candidates if item.emoji_id != self.recent_ids[-1]]
            if without_last:
                pool = without_last
        chosen = self._random.choice(pool)
        self.recent_ids.append(chosen.emoji_id)
        self.last_selected = chosen.emoji_id
        return EmojiResult(status="matched", emoji_id=chosen.emoji_id, path=chosen.path, score=chosen.score)

    def build_context(self) -> str:
        """Expose enabled expression attributes without internal IDs or file paths."""
        if not self.enabled or not any(item.enabled for item in self.entries):
            return ""
        catalog = "\n".join(f"- 属性：{'、'.join(item.tags)}" for item in self.entries if item.enabled)
        return (
            "\n\n当前可用表情：\n" + catalog + "\n\n"
            "你可以在回复中使用当前提供的表情，格式为 [emoji:属性1,属性2]。\n"
            "规则：只使用上面实际存在的属性；每次选择 1~3 个最贴切属性；"
            "只有 [emoji:...] 才会发送图片，不要直接照抄属性列表；没有合适表情时不要输出 emoji DSL；表情可放在开头、中间或结尾，也可以不用；"
            "严肃任务和长篇技术说明中少用；不要输出具体 emoji_id；不要解释 DSL。"
        )

    def resolve_tags(self, requested_tags: list[str]) -> EmojiResult:
        """Resolve exact registry attributes with simple overlap and recency scoring."""
        tags = list(dict.fromkeys(item.strip() for item in requested_tags if item.strip()))[:3]
        self.last_requested_tags = tags
        self.last_intent = ",".join(tags)
        if not self.enabled or not self.entries or not tags:
            self.last_candidates = []
            self.last_selected = None
            return EmojiResult(status="no_match")
        requested = {item.casefold() for item in tags}
        candidates: list[EmojiCandidate] = []
        for entry in self.entries:
            available = {item.casefold() for item in entry.tags}
            hits = len(requested & available)
            if not hits:
                continue
            coverage = hits / len(requested)
            specificity = hits / max(1, len(available))
            score = .55 * coverage + .35 * min(1.0, hits / 3) + .10 * specificity
            if entry.id in self.recent_ids:
                distance = list(reversed(self.recent_ids)).index(entry.id)
                score -= .30 if distance == 0 else max(.08, .20 - distance * .04)
            candidates.append(EmojiCandidate(
                emoji_id=entry.id,
                path=str((self.registry_path.parent / entry.file).resolve()),
                description=entry.description,
                emotion=entry.emotion,
                intensity=entry.intensity,
                score=round(min(1.0, max(0.0, score)), 4),
            ))
        candidates.sort(key=lambda item: (-item.score, item.emoji_id))
        self.last_candidates = candidates[:self.candidate_limit]
        if not candidates:
            self.last_selected = None
            return EmojiResult(status="no_match")
        best = candidates[0].score
        pool = [item for item in candidates if item.score >= best - .03]
        chosen = self._random.choice(pool)
        self.recent_ids.append(chosen.emoji_id)
        self.last_selected = chosen.emoji_id
        return EmojiResult(
            status="matched", emoji_id=chosen.emoji_id, path=chosen.path, score=chosen.score
        )

    def diagnostics(self) -> dict:
        return {
            "enabled": self.enabled,
            "loaded_emojis": len(self.entries),
            "load_error": self.load_error,
            "last_intent": self.last_intent,
            "current_emoji_context": self.build_context(),
            "requested_tags": self.last_requested_tags,
            "candidates": [{"emoji_id": item.emoji_id, "score": item.score} for item in self.last_candidates],
            "selected": self.last_selected,
            "recent": list(self.recent_ids),
        }
