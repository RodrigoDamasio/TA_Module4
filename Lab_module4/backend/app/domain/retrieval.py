"""Search modes and hits (with every score that explains the rank)."""

from dataclasses import dataclass, field
from enum import StrEnum

from .chunks import Chunk


class SearchMode(StrEnum):
    VECTOR = "vector"
    BM25 = "bm25"
    HYBRID = "hybrid"
    HYBRID_RERANK = "hybrid_rerank"


@dataclass(frozen=True)
class Scores:
    vector: float | None = None  # cosine similarity (1 - distance)
    bm25: float | None = None
    rrf: float | None = None
    rerank: float | None = None
    ranks: dict[str, int] = field(default_factory=dict)  # {"vector": 3, "bm25": 1, ...}

    def as_dict(self) -> dict:
        return {
            "vector": self.vector,
            "bm25": self.bm25,
            "rrf": self.rrf,
            "rerank": self.rerank,
            "ranks": dict(self.ranks),
        }


@dataclass(frozen=True)
class SearchHit:
    chunk: Chunk
    scores: Scores
    rank: int  # 1-based, final order


@dataclass(frozen=True)
class Candidate:
    """One entry of an intermediate ranked list (vector, BM25, fused, reranked)."""

    chunk_id: str
    score: float
    rank: int
    extra: dict = field(default_factory=dict)  # distance, matched_terms, rank_before, …


@dataclass
class RetrievalDebug:
    """The intermediate lists of one search — returned only with ?debug=true (§10.1)."""

    query_embedding: dict | None = None
    vector: list[Candidate] = field(default_factory=list)
    bm25: list[Candidate] = field(default_factory=list)
    fused: list[Candidate] = field(default_factory=list)
    reranked: list[Candidate] | None = None
    rerank_skipped: str | None = None  # "disabled" | "mode=hybrid" | "loading" | ...


@dataclass
class SearchResult:
    hits: list[SearchHit]
    mode: SearchMode  # the mode actually used
    debug: RetrievalDebug
    chunks: dict[str, Chunk] = field(default_factory=dict)  # every chunk in any list
