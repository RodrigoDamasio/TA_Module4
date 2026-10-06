"""ChromaVectorStore (§7.3): one persistent collection per embedding model, cosine HNSW,
our own vectors (Chroma's embedding function is never used), codebase filter on query.

The document stored with each record is the chunk's code; the header and line numbers are
metadata, so `Chunk.embed_text` is rebuilt exactly when the BM25 index is rebuilt."""

import re
import threading
from collections.abc import Iterator

import chromadb
from chromadb.config import Settings

from app.domain.chunks import Chunk

PAGE = 500


def collection_name(model: str) -> str:
    """Chroma names: 3-63 chars of [a-zA-Z0-9._-], starting and ending alphanumeric."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", model).strip("-").lower()
    return f"chunks-{slug}"[:63].rstrip("-.")


def _where(codebase: str | None = None, path: str | None = None) -> dict | None:
    clauses = []
    if codebase is not None:
        clauses.append({"codebase": codebase})
    if path is not None:
        clauses.append({"path": path})
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


class ChromaVectorStore:
    def __init__(self, path: str, model: str) -> None:
        self._client = chromadb.PersistentClient(
            path=path, settings=Settings(anonymized_telemetry=False)
        )
        self._collection = self._client.get_or_create_collection(
            collection_name(model), metadata={"hnsw:space": "cosine"}, embedding_function=None
        )
        self._lock = threading.Lock()  # one writer at a time (API threads + the job worker)

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if not chunks:
            return
        with self._lock:
            for start in range(0, len(chunks), PAGE):
                batch = chunks[start : start + PAGE]
                self._collection.upsert(
                    ids=[c.id for c in batch],
                    embeddings=vectors[start : start + PAGE],
                    documents=[c.code for c in batch],
                    metadatas=[c.to_metadata() for c in batch],
                )

    def _ids(self, where: dict | None) -> list[str]:
        return list(self._collection.get(where=where, include=[])["ids"])

    def delete_file(self, codebase: str, path: str) -> int:
        with self._lock:
            ids = self._ids(_where(codebase, path))
            if ids:
                self._collection.delete(ids=ids)
            return len(ids)

    def delete_codebase(self, codebase: str) -> int:
        with self._lock:
            ids = self._ids(_where(codebase))
            if ids:
                self._collection.delete(ids=ids)
            return len(ids)

    def query(self, vector: list[float], codebases: list[str], n: int) -> list[tuple[str, float]]:
        if not codebases or self._collection.count() == 0:
            return []
        where = (
            {"codebase": codebases[0]} if len(codebases) == 1 else {"codebase": {"$in": codebases}}
        )
        result = self._collection.query(
            query_embeddings=[vector], n_results=n, where=where, include=["distances"]
        )
        ids = result["ids"][0] if result["ids"] else []
        distances = (result.get("distances") or [[]])[0]
        return list(zip(ids, (float(d) for d in distances), strict=True))

    def get(self, ids: list[str]) -> list[Chunk]:
        if not ids:
            return []
        result = self._collection.get(ids=ids, include=["documents", "metadatas"])
        return _chunks(result)

    def iter_chunks(self, codebase: str | None = None, path: str | None = None) -> Iterator[Chunk]:
        where = _where(codebase, path)
        offset = 0
        while True:
            result = self._collection.get(
                where=where, include=["documents", "metadatas"], limit=PAGE, offset=offset
            )
            chunks = _chunks(result)
            yield from chunks
            if len(chunks) < PAGE:
                return
            offset += PAGE

    def count(self, codebase: str | None = None) -> int:
        if codebase is None:
            return self._collection.count()
        return len(self._ids(_where(codebase)))


def _chunks(result) -> list[Chunk]:
    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or []
    return [
        Chunk.from_metadata(i, doc or "", dict(meta or {}))
        for i, doc, meta in zip(result["ids"], documents, metadatas, strict=True)
    ]
