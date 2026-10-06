"""Embedding with the cache in front (extension: caching, layer 2). Vectors are keyed by
model + SHA-256 of the exact text, so identical text is never embedded twice."""

from typing import Protocol

from app.domain.chunks import sha256
from app.domain.ports import Embedder, EmbeddingCache, Reranker


class Models(Protocol):
    """Where the retriever and indexer get their models. The ONNX implementation loads them
    in the background, so `embedder()` may raise ModelsLoading."""

    def embedder(self) -> Embedder: ...

    def reranker(self) -> tuple[Reranker | None, str | None]:
        """(reranker, None) when ready, or (None, reason) — "disabled" / "loading"."""
        ...

    def wait_ready(self, timeout_s: float) -> bool: ...

    def status(self) -> str: ...


class CachedEmbeddings:
    def __init__(self, cache: EmbeddingCache) -> None:
        self._cache = cache

    def documents(self, embedder: Embedder, texts: list[str]) -> tuple[list[list[float]], int]:
        """(vectors in input order, number of cache hits)."""
        keys = [sha256(t) for t in texts]
        found = self._cache.get_many(embedder.name, list(dict.fromkeys(keys)))
        missing = [i for i, k in enumerate(keys) if k not in found]
        unique_missing = list(dict.fromkeys(keys[i] for i in missing))
        if unique_missing:
            first_text = {keys[i]: texts[i] for i in missing}
            vectors = embedder.embed_documents([first_text[k] for k in unique_missing])
            new = dict(zip(unique_missing, vectors, strict=True))
            self._cache.put_many(embedder.name, new)
            found |= new
        return [found[k] for k in keys], len(texts) - len(missing)

    def query(self, embedder: Embedder, text: str) -> tuple[list[float], bool]:
        """Query vectors use a separate key space ('q:'): models like bge add an
        instruction prefix to queries, so a query and a document with the same text differ."""
        key = sha256("q:" + text)
        found = self._cache.get_many(embedder.name, [key])
        if key in found:
            return found[key], True
        vector = embedder.embed_query(text)
        self._cache.put_many(embedder.name, {key: vector})
        return vector, False
