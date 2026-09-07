"""Small local embedding provider and O(n) cosine helpers."""

import hashlib
import math
import re
from typing import Protocol


class EmbeddingProvider(Protocol):
    model: str

    async def embed(self, text: str) -> list[float]: ...


class LocalHashEmbeddingProvider:
    """Dependency-free, deterministic lexical-semantic baseline.

    It hashes normalized words and CJK bigrams into a signed feature vector.  A
    configured model provider can replace it without changing persistence.
    """

    model = "local-hash-v1"

    def __init__(self, dimensions: int = 256) -> None:
        self.dimensions = dimensions

    async def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in self._tokens(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "big")
            vector[value % self.dimensions] += 1.0 if value & 1 else -1.0
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector

    @staticmethod
    def content_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _tokens(text: str) -> set[str]:
        folded = text.casefold()
        words = set(re.findall(r"[a-z0-9_]+", folded))
        cjk = "".join(re.findall(r"[\u4e00-\u9fff]", folded))
        words.update(cjk[index:index + 2] for index in range(max(0, len(cjk) - 1)))
        return {item for item in words if item}


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    return max(0.0, sum(a * b for a, b in zip(left, right)))
