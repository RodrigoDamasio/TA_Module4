"""The four search modes (§8.1): vector · bm25 · hybrid (RRF) · hybrid_rerank (default).

Every hit carries all the scores and ranks that explain it, and every intermediate list is
kept in a RetrievalDebug (returned only with ?debug=true)."""

from dataclasses import dataclass

from app.domain.chunks import Chunk
from app.domain.errors import CodebaseNotFound, EmptyIndex
from app.domain.ports import IndexRepository, VectorStore
from app.domain.retrieval import (
    Candidate,
    RetrievalDebug,
    Scores,
    SearchHit,
    SearchMode,
    SearchResult,
)

from ..embedding import CachedEmbeddings, Models
from ..tracing import Tracer
from .bm25 import BM25Index
from .fusion import rrf


@dataclass(frozen=True)
class RetrievalSettings:
    candidates: int = 20
    rerank_max_chars: int = 800
    vector_weight: float = 0.7  # course §3.3 hybrid weights
    bm25_weight: float = 0.3


class Retriever:
    def __init__(
        self,
        store: VectorStore,
        bm25: BM25Index,
        models: Models,
        embeddings: CachedEmbeddings,
        index: IndexRepository,
        settings: RetrievalSettings,
    ) -> None:
        self._store, self._bm25, self._models = store, bm25, models
        self._embeddings, self._index, self._settings = embeddings, index, settings

    def check_codebases(self, codebases: list[str]) -> None:
        empty = []
        for cb in codebases:
            record = self._index.get_codebase(cb)
            if record is None:
                raise CodebaseNotFound(cb)
            if record.chunk_count == 0:
                empty.append(cb)
        if len(empty) == len(codebases):
            raise EmptyIndex(empty)

    def search(
        self, query: str, codebases: list[str], k: int, mode: SearchMode, tracer: Tracer
    ) -> SearchResult:
        self.check_codebases(codebases)
        n = self._settings.candidates
        debug = RetrievalDebug()
        vector_ids: list[str] = []
        similarity: dict[str, float] = {}
        bm25_ids: list[str] = []
        bm25_score: dict[str, float] = {}

        if mode is not SearchMode.BM25:
            embedder = self._models.embedder()
            with tracer.span("embed_query") as s:
                vector, cached = self._embeddings.query(embedder, query)
                s |= {"model": embedder.name, "cached": cached}
            debug.query_embedding = {
                "model": embedder.name,
                "dims": len(vector),
                "cached": cached,
                "ms": round(tracer.spans[-1].ms, 1),
            }
            with tracer.span("vector_search") as s:
                hits = self._store.query(vector, codebases, n)
                vector_ids = [i for i, _ in hits]
                similarity = {i: 1.0 - d for i, d in hits}
                debug.vector = [
                    Candidate(i, 1.0 - d, r, {"distance": d}) for r, (i, d) in enumerate(hits, 1)
                ]
                s |= _score_attrs("similarity", [1.0 - d for _, d in hits])

        if mode is not SearchMode.VECTOR:
            with tracer.span("bm25") as s:
                keyword = self._bm25.search(query, codebases, n)
                bm25_ids = [h.chunk_id for h in keyword]
                bm25_score = {h.chunk_id: h.score for h in keyword}
                debug.bm25 = [
                    Candidate(h.chunk_id, h.score, r, {"matched_terms": h.matched_terms})
                    for r, h in enumerate(keyword, 1)
                ]
                s |= _score_attrs("score", [h.score for h in keyword])

        ranks: dict[str, dict[str, int]] = {}
        rrf_score: dict[str, float] = {}
        if mode is SearchMode.VECTOR:
            order = vector_ids
        elif mode is SearchMode.BM25:
            order = bm25_ids
        else:
            with tracer.span("fuse") as s:
                weights = {"vector": self._settings.vector_weight,
                           "bm25": self._settings.bm25_weight}  # fmt: skip
                fused = rrf({"vector": vector_ids, "bm25": bm25_ids}, weights=weights)
                order = [f.chunk_id for f in fused][:n]
                ranks = {f.chunk_id: f.ranks for f in fused}
                rrf_score = {f.chunk_id: f.score for f in fused}
                debug.fused = [
                    Candidate(f.chunk_id, f.score, r, dict(f.ranks))
                    for r, f in enumerate(fused[:n], 1)
                ]
                s["overlap"] = len(set(vector_ids) & set(bm25_ids))

        all_ids = list(dict.fromkeys(vector_ids + bm25_ids))
        chunks = {c.id: c for c in self._store.get(all_ids)} if all_ids else {}
        order = [i for i in order if i in chunks]

        rerank_score: dict[str, float] = {}
        used = mode
        if mode is SearchMode.HYBRID_RERANK:
            reranker, reason = self._models.reranker()
            if reranker is None:
                debug.rerank_skipped = reason
                used = SearchMode.HYBRID
            elif order:
                with tracer.span("rerank") as s:
                    limit = self._settings.rerank_max_chars
                    texts = [_rerank_text(chunks[i], limit) for i in order]
                    scores = reranker.score(query, texts)
                    before = {i: r for r, i in enumerate(order, 1)}
                    rerank_score = dict(zip(order, scores, strict=True))
                    order = sorted(order, key=lambda i: (-rerank_score[i], before[i]))
                    debug.reranked = [
                        Candidate(i, rerank_score[i], r, {"rank_before": before[i]})
                        for r, i in enumerate(order[:k], 1)
                    ]
                    s |= {"candidates": len(texts), "model": reranker.name}
                    s |= _score_attrs("score", scores)
        elif mode is SearchMode.HYBRID:
            debug.rerank_skipped = "mode=hybrid"

        final = order[:k]
        hits = [
            SearchHit(
                chunk=chunks[i],
                scores=Scores(
                    vector=similarity.get(i),
                    bm25=bm25_score.get(i),
                    rrf=rrf_score.get(i),
                    rerank=rerank_score.get(i),
                    ranks=ranks.get(i, _single_rank(i, vector_ids, bm25_ids)),
                ),
                rank=r,
            )
            for r, i in enumerate(final, 1)
        ]
        return SearchResult(hits=hits, mode=used, debug=debug, chunks=chunks)


def _rerank_text(chunk: Chunk, limit: int) -> str:
    return (chunk.header + "\n" + chunk.code)[:limit] if chunk.header else chunk.code[:limit]


def _single_rank(chunk_id: str, vector_ids: list[str], bm25_ids: list[str]) -> dict[str, int]:
    ranks = {}
    if chunk_id in vector_ids:
        ranks["vector"] = vector_ids.index(chunk_id) + 1
    if chunk_id in bm25_ids:
        ranks["bm25"] = bm25_ids.index(chunk_id) + 1
    return ranks


def _score_attrs(name: str, values: list[float]) -> dict:
    if not values:
        return {"candidates": 0}
    return {
        "candidates": len(values),
        f"top_{name}": round(max(values), 4),
        f"low_{name}": round(min(values), 4),
    }
