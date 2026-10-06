"""EMBED_MODE=fake: deterministic, dependency-free models for tests, E2E and UI work.

HashingEmbedder hashes the code-aware tokens (the BM25 tokenizer) into a fixed-size vector,
so texts that share identifiers really are close — retrieval tests stay meaningful."""

import hashlib
import math

from app.application.retrieval.bm25 import tokenize
from app.domain.ports import Embedder, Reranker


class HashingEmbedder:
    def __init__(self, dim: int = 256, name: str = "fake-hashing-256") -> None:
        self.name, self.dim, self.max_tokens = name, dim, 10**6
        self.calls = 0  # texts embedded (tests check the cache)

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in tokenize(text):
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls += len(texts)
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        self.calls += 1
        return self._vector(text)


class OverlapReranker:
    """Scores (query, text) by the share of query tokens found in the text."""

    name = "fake-overlap"

    def score(self, query: str, texts: list[str]) -> list[float]:
        terms = set(tokenize(query))
        return [len(terms & set(tokenize(t))) / (len(terms) or 1) for t in texts]


class FakeModels:
    def __init__(
        self,
        embedder: Embedder | None = None,
        reranker: Reranker | None = None,
        rerank_disabled: bool = False,
    ) -> None:
        self._embedder = embedder or HashingEmbedder()
        self._reranker = reranker or OverlapReranker()
        self._disabled = rerank_disabled

    def embedder(self) -> Embedder:
        return self._embedder

    def reranker(self) -> tuple[Reranker | None, str | None]:
        return (None, "disabled") if self._disabled else (self._reranker, None)

    def wait_ready(self, timeout_s: float) -> bool:
        return True

    def status(self) -> str:
        return "ready"
