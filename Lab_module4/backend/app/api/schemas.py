"""Request models and response views (§11). Code and questions appear only here — in the
HTTP response to the caller — never in logs or stored traces."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domain.answers import Answer
from app.domain.chunks import Chunk
from app.domain.codebases import Codebase, FileRecord
from app.domain.jobs import Job
from app.domain.retrieval import Candidate, SearchHit, SearchMode, SearchResult
from app.domain.tracing import PipelineDebug, Trace

# ---- requests ------------------------------------------------------------------------


class FileIn(BaseModel):
    path: str = Field(min_length=1, max_length=200)
    content: str


class IndexRequest(BaseModel):
    codebase: str = Field(min_length=1, max_length=40)
    files: list[FileIn] = Field(min_length=1)


QUESTION_MAX_CHARS = 500


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=QUESTION_MAX_CHARS)
    codebases: list[str] = Field(min_length=1, max_length=10)
    k: int | None = Field(default=None, ge=1, le=20)
    mode: SearchMode | None = None  # None = the server's DEFAULT_MODE


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=QUESTION_MAX_CHARS)
    codebases: list[str] = Field(min_length=1, max_length=10)
    k: int | None = Field(default=None, ge=1, le=20)
    mode: SearchMode | None = None  # None = the server's DEFAULT_MODE


class EvaluateRequest(BaseModel):
    mode: Literal["retrieval", "full"] = "retrieval"
    dataset: Literal["builtin", "custom"] = "builtin"
    examples: list[dict[str, Any]] | None = None
    k: int | None = Field(default=None, ge=1, le=20)
    search_mode: SearchMode | None = None
    max_calls: int | None = Field(default=None, ge=0, le=200)


# ---- views ---------------------------------------------------------------------------


def chunk_view(chunk: Chunk, with_code: bool = True) -> dict[str, Any]:
    view: dict[str, Any] = {
        "chunk_id": chunk.id,
        "codebase": chunk.codebase,
        "path": chunk.path,
        "language": chunk.language.value,
        "kind": chunk.kind.value,
        "symbol": chunk.symbol,
        "signature": chunk.signature,
        "start_line": chunk.start_line,
        "end_line": chunk.end_line,
        "part": list(chunk.part) if chunk.part else None,
    }
    if with_code:
        view["code"] = chunk.code
    return view


def source_view(hit: SearchHit) -> dict[str, Any]:
    return {"n": hit.rank, **chunk_view(hit.chunk), "scores": hit.scores.as_dict()}


def trace_view(trace: Trace) -> dict[str, Any]:
    return trace.as_dict()


def codebase_view(codebase: Codebase) -> dict[str, Any]:
    return {
        "id": codebase.id,
        "kind": codebase.kind.value,
        "read_only": codebase.read_only,
        "file_count": codebase.file_count,
        "chunk_count": codebase.chunk_count,
        "bytes": codebase.bytes,
        "languages": codebase.languages,
        "created_at": codebase.created_at,
        "updated_at": codebase.updated_at,
        "expires_at": codebase.expires_at,
    }


def file_view(record: FileRecord) -> dict[str, Any]:
    return {
        "path": record.path,
        "language": record.language.value,
        "chunk_count": record.chunk_count,
        "bytes": record.bytes,
        "fallback": record.fallback,
        "indexed_at": record.indexed_at,
    }


def job_view(job: Job) -> dict[str, Any]:
    data = job.to_dict()
    data["status_url"] = f"/jobs/{job.id}"
    return data


def answer_view(answer: Answer) -> dict[str, Any]:
    return {
        "answer": answer.text,
        "found": answer.found,
        "grounded": answer.grounded,
        "citations": answer.citations,
        "sources": [source_view(h) for h in answer.sources],
    }


# ---- pipeline debug (?debug=true, §10.1) ---------------------------------------------------


def _candidate(c: Candidate, chunks: dict[str, Chunk], score_name: str) -> dict[str, Any]:
    chunk = chunks.get(c.chunk_id)
    location = (
        {
            "codebase": chunk.codebase,
            "path": chunk.path,
            "symbol": chunk.symbol,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
        }
        if chunk
        else {}
    )
    return {
        "rank": c.rank,
        "chunk_id": c.chunk_id,
        **location,
        score_name: round(c.score, 6),
        **{k: (round(v, 6) if isinstance(v, float) else v) for k, v in c.extra.items()},
    }


def pipeline_view(
    debug: PipelineDebug | None, result: SearchResult, question: str
) -> dict[str, Any]:
    retrieval = result.debug
    chunks = result.chunks
    view: dict[str, Any] = {
        "question": question,
        "query_rewrite": debug.query_rewrite if debug else None,
        "query_embedding": retrieval.query_embedding,
        "vector_candidates": [_candidate(c, chunks, "similarity") for c in retrieval.vector],
        "bm25_candidates": [_candidate(c, chunks, "score") for c in retrieval.bm25],
        "rrf_merged": [_candidate(c, chunks, "rrf") for c in retrieval.fused],
        "reranked": (
            [_candidate(c, chunks, "rerank") for c in retrieval.reranked]
            if retrieval.reranked is not None
            else None
        ),
        "rerank_skipped": retrieval.rerank_skipped,
    }
    if debug is not None and debug.prompt is not None:
        view["prompt"] = {
            "prompt_version": debug.prompt.prompt_version,
            "est_tokens": debug.prompt.est_tokens,
            "chunks_sent": debug.prompt.chunks_sent,
            "chunks_dropped": debug.prompt.chunks_dropped,
            "system": debug.prompt.system,
            "user": debug.prompt.user,
        }
        view["llm"] = {
            "cached": debug.llm_cached,
            "input_tokens": debug.input_tokens,
            "output_tokens": debug.output_tokens,
            "raw_output": debug.attempts[-1].raw_output if debug.attempts else None,
            "attempts": [
                {
                    "raw_output": a.raw_output,
                    "errors": a.errors,
                    "repair_message": a.repair_message,
                }
                for a in debug.attempts
            ],
        }
    return view
