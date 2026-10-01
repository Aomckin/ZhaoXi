"""Versioned embedding providers and bounded cosine scoring."""

import hashlib
import math
import re
from typing import Protocol


class EmbeddingProvider(Protocol):
    model: str

    async def embed(self, text: str) -> list[float]: ...


class LocalHashEmbeddingProvider:
    """Dependency-free, deterministic lexical fallback.

    It hashes normalized words and CJK bigrams into a signed feature vector.  A
    configured model provider can replace it without changing persistence.
    """

    model = "local-hash-v1"
    version = "1"

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
    norm = math.sqrt(sum(a*a for a in left) * sum(b*b for b in right))
    return max(0.0, min(1.0, sum(a * b for a, b in zip(left, right)) / norm)) if norm else 0.0


class SemanticEmbeddingProvider:
    """Opt-in semantic /embeddings endpoint; failures never silently mix spaces."""
    def __init__(self, *, base_url: str, api_key: str, model: str, version: str = "1",
                 dimensions: int = 1536, timeout: float = 30, client=None):
        self.base_url, self.api_key, self.model = base_url.rstrip("/"), api_key, model
        self.version, self.dimensions, self.timeout, self.client = version, dimensions, timeout, client

    content_hash = staticmethod(LocalHashEmbeddingProvider.content_hash)

    async def embed(self, text: str) -> list[float]:
        return (await self.embed_many([text]))[0]

    async def embed_many(self, texts: list[str]) -> list[list[float]]:
        """One bounded offline batch, preserving input order by response index."""
        import httpx
        if not texts:
            return []
        if len(texts) > 10:
            raise ValueError("embedding batch must contain at most 10 texts")
        async def request(client):
            response = await client.post(self.base_url + "/embeddings",
                headers={"Authorization": "Bearer " + self.api_key},
                json={"model": self.model, "input": texts, "dimensions": self.dimensions,
                      "encoding_format": "float"}, timeout=self.timeout)
            response.raise_for_status()
            try:
                rows = response.json()["data"]
                if len(rows) != len(texts):
                    raise ValueError("embedding batch size mismatch")
                if len(texts) > 1:
                    indices = [row["index"] for row in rows]
                    if sorted(indices) != list(range(len(texts))):
                        raise ValueError("embedding batch indices mismatch")
                    rows = sorted(rows, key=lambda row: row["index"])
                vectors = [[float(x) for x in row["embedding"]] for row in rows]
            except (KeyError, IndexError, TypeError) as error:
                raise ValueError("invalid embedding response shape") from error
            normalized = []
            for vector in vectors:
                if len(vector) != self.dimensions or not all(math.isfinite(x) for x in vector):
                    raise ValueError("embedding dimension or values do not match configured space")
                norm = math.sqrt(sum(x*x for x in vector))
                if not norm:
                    raise ValueError("zero semantic embedding")
                normalized.append([x / norm for x in vector])
            return normalized
        if self.client is not None:
            return await request(self.client)
        async with httpx.AsyncClient() as client:
            return await request(client)


def embedding_space(provider):
    return (provider.model, getattr(provider, "version", "1"), getattr(provider, "dimensions", 256))


def compatible(provider, embedding):
    return embedding_space(provider) == (embedding.embedding_model, embedding.embedding_version, embedding.embedding_dim)


def provider_from_settings(settings):
    """A configured semantic space must never silently become lexical hash."""
    from zhaoxi.errors import ConfigError
    if settings.memory_embedding_model == 'local-hash-v1':
        if settings.memory_embedding_base_url:
            raise ConfigError('配置语义 Embedding URL 时也必须填写对应模型名。')
        return LocalHashEmbeddingProvider(dimensions=settings.memory_embedding_dim)
    if not settings.memory_embedding_base_url:
        raise ConfigError('语义 Embedding 模型需要 ZHAOXI_MEMORY_EMBEDDING_BASE_URL。')
    return SemanticEmbeddingProvider(base_url=settings.memory_embedding_base_url,
        api_key=settings.memory_embedding_api_key, model=settings.memory_embedding_model,
        version=settings.memory_embedding_version, dimensions=settings.memory_embedding_dim)
