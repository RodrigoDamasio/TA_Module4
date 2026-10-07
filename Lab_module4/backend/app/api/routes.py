"""HTTP endpoints (§11). Thin: validate, rate-limit, call a service, shape the response.

Endpoints are sync `def`s on purpose: FastAPI runs them in its thread pool, so CPU-bound
work (embedding a query, reranking) never blocks the event loop."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response

from app.application.evaluation.service import MAX_CUSTOM_EXAMPLES
from app.application.tracing import Tracer
from app.domain.chunks import CHUNKER_VERSION
from app.domain.codebases import CODEBASE_ID_PATTERN
from app.domain.errors import InvalidPath
from app.domain.files import (
    EXTENSIONS,
    LOCKFILES,
    MAX_PATH_CHARS,
    MINIFIED_LINE_CHARS,
    SKIPPED_DIRS,
    SourceFile,
)
from app.domain.retrieval import SearchMode

from .dependencies import Container, get_container
from .problems import PROBLEM_RESPONSE, WaitTimeout
from .schemas import (
    QUESTION_MAX_CHARS,
    EvaluateRequest,
    IndexRequest,
    QueryRequest,
    SearchRequest,
    answer_view,
    chunk_view,
    codebase_view,
    file_view,
    job_view,
    pipeline_view,
    source_view,
)

router = APIRouter()
logger = logging.getLogger("app.api")
ERRORS: dict[int | str, dict[str, Any]] = {
    code: PROBLEM_RESPONSE for code in (404, 409, 413, 422, 429, 502, 503, 504)
}


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _k(container: Container, k: int | None) -> int:
    return min(k or container.settings.default_k, container.settings.max_k)


def _mode(container: Container, mode: SearchMode | None) -> SearchMode:
    return mode or SearchMode(container.settings.default_mode)


def _debug_enabled(container: Container, requested: bool) -> tuple[bool, str | None]:
    if not requested:
        return False, None
    if not container.settings.pipeline_debug_enabled:
        return False, "disabled"
    return True, "enabled"


def _meta(container: Container, mode: SearchMode, k: int, debug: str | None) -> dict[str, Any]:
    s = container.settings
    meta = {
        "mode": mode.value,
        "k": k,
        "embedder": s.embedder_name,
        "reranker": s.rerank_model
        if s.embed_mode == "onnx" or not s.rerank_model
        else "fake-overlap",
        "chunker_version": CHUNKER_VERSION,
        "model": s.llm_name,
        "prompt_version": container.prompts.version,
    }
    if debug:
        meta["debug"] = debug
    return meta


# ---- indexing ------------------------------------------------------------------------------


@router.post("/index/files", status_code=202, responses=ERRORS, tags=["indexing"])
def index_files(
    body: IndexRequest,
    request: Request,
    response: Response,
    wait: bool = Query(False, description="Block until the index job finishes (200)."),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    """Index (or re-index) code files into a codebase. Runs as a background job because
    local embedding takes ~150 ms per chunk; `?wait=true` returns the finished result."""
    container.limiters.index.check(client_ip(request))
    files = [SourceFile(f.path, f.content) for f in body.files]
    job = container.jobs.submit_index(body.codebase, files)
    logger.info("index submitted job=%s codebase=%s files=%d", job.id, body.codebase, len(files))
    response.headers["Location"] = f"/jobs/{job.id}"
    if not wait:
        return job_view(job)
    job = container.jobs.wait(job.id, container.settings.sync_wait_timeout_s)
    if not job.done:
        raise WaitTimeout(job.id, container.settings.sync_wait_timeout_s)
    response.status_code = 200
    return job_view(job)


@router.get("/jobs/{job_id}", responses=ERRORS, tags=["jobs"])
def get_job(job_id: str, container: Container = Depends(get_container)) -> dict[str, Any]:
    return job_view(container.jobs.get(job_id))


@router.get("/codebases", tags=["codebases"])
def list_codebases(container: Container = Depends(get_container)) -> list[dict[str, Any]]:
    return [codebase_view(c) for c in container.codebases.all()]


@router.get("/codebases/{codebase}", responses=ERRORS, tags=["codebases"])
def get_codebase(codebase: str, container: Container = Depends(get_container)) -> dict[str, Any]:
    record = container.codebases.get(codebase)
    files = container.codebases.files(codebase)
    return codebase_view(record) | {"files": [file_view(f) for f in files]}


@router.get("/codebases/{codebase}/chunks", responses=ERRORS, tags=["codebases"])
def get_chunks(
    codebase: str,
    path: str = Query(..., min_length=1, max_length=200),
    container: Container = Depends(get_container),
) -> list[dict[str, Any]]:
    """The chunks one file was split into (what got indexed)."""
    return [
        chunk_view(c) | {"header": c.header} for c in container.codebases.chunks(codebase, path)
    ]


@router.delete("/codebases/{codebase}", status_code=204, responses=ERRORS, tags=["codebases"])
def delete_codebase(codebase: str, container: Container = Depends(get_container)) -> Response:
    container.codebases.delete(codebase)
    return Response(status_code=204)


# ---- search and query ------------------------------------------------------------------------


@router.post("/search", responses=ERRORS, tags=["query"])
def search(
    body: SearchRequest,
    request: Request,
    debug: bool = Query(False, description="Add every intermediate ranking (§10.1)."),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    """Semantic code search only: 0 LLM calls."""
    container.limiters.search.check(client_ip(request))
    k = _k(container, body.k)
    show, debug_state = _debug_enabled(container, debug)
    tracer = Tracer("search")
    mode = _mode(container, body.mode)
    result = container.retriever.search(body.query, body.codebases, k, mode, tracer)
    trace = tracer.finish(mode=result.mode.value, k=k, hits=len(result.hits),
                          query_chars=len(body.query))  # fmt: skip
    container.traces.save(trace)
    out: dict[str, Any] = {
        "request_id": trace.request_id,
        "hits": [source_view(h) for h in result.hits],
        "trace": trace.as_dict(),
        "meta": _meta(container, result.mode, k, debug_state),
    }
    if show:
        out["pipeline"] = pipeline_view(None, result, body.query)
    return out


@router.post("/query", responses=ERRORS, tags=["query"])
def query(
    body: QueryRequest,
    request: Request,
    debug: bool = Query(False, description="Add every transformation and the exact prompt."),
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    """Answer a question from the indexed code, with citations and sources (1 LLM call,
    0 when the same question meets the same retrieved code again)."""
    container.limiters.query.check(client_ip(request))
    k = _k(container, body.k)
    show, debug_state = _debug_enabled(container, debug)
    tracer = Tracer("query")
    answer, result, pipeline = container.answers.answer(
        body.question, body.codebases, k, _mode(container, body.mode), tracer
    )
    trace = tracer.finish(
        mode=result.mode.value,
        k=k,
        question_chars=len(body.question),
        found=answer.found,
        grounded=answer.grounded,
        llm_cached=answer.cached,
        cache={"llm": answer.cached, "query_embedding": _span_flag(tracer, "embed_query")},
    )
    container.traces.save(trace)
    out = {
        "request_id": trace.request_id,
        **answer_view(answer),
        "trace": trace.as_dict(),
        "meta": _meta(container, result.mode, k, debug_state),
    }
    if show:
        out["pipeline"] = pipeline_view(pipeline, result, body.question)
    return out


def _span_flag(tracer: Tracer, name: str) -> bool | None:
    span = next((s for s in tracer.spans if s.name == name), None)
    return bool(span.attrs.get("cached")) if span else None


# ---- evaluation ------------------------------------------------------------------------------


@router.post("/evaluate", responses=ERRORS, tags=["evaluation"])
def evaluate(
    body: EvaluateRequest,
    request: Request,
    response: Response,
    container: Container = Depends(get_container),
) -> dict[str, Any]:
    """`retrieval`: synchronous, 0 LLM calls (P@K, R@K, MRR). `full`: answers + LLM judge as a
    background job (202 + Location); its real calls are capped by FULL_EVAL_MAX_CALLS, so in
    production it replays cached answers only."""
    container.limiters.search.check(client_ip(request))
    evaluations = container.evaluations
    if body.mode == "retrieval":
        examples = (
            evaluations.custom(body.examples or [])
            if body.dataset == "custom"
            else evaluations.builtin()
        )
        return evaluations.run_retrieval(examples, body.k, body.search_mode)
    if body.dataset == "custom":
        raise InvalidPath("Custom datasets run in retrieval mode only.", pointer="#/dataset")
    job = container.jobs.submit_evaluation(
        {
            "k": body.k,
            "search_mode": body.search_mode.value if body.search_mode else None,
            "max_calls": body.max_calls,
        }
    )
    response.status_code = 202
    response.headers["Location"] = f"/jobs/{job.id}"
    return job_view(job)


@router.get("/evaluations", tags=["evaluation"])
def list_evaluations(container: Container = Depends(get_container)) -> list[dict[str, Any]]:
    return container.evaluations.all()


@router.get("/evaluations/{report_id}", responses=ERRORS, tags=["evaluation"])
def get_evaluation(report_id: str, container: Container = Depends(get_container)) -> dict:
    return container.evaluations.get(report_id)


@router.get("/datasets/builtin", tags=["evaluation"])
def builtin_dataset(container: Container = Depends(get_container)) -> list[dict[str, Any]]:
    """The 20 built-in questions (also the UI's suggested questions)."""
    return [
        {
            "id": e.id,
            "question": e.question,
            "category": e.category,
            "codebases": e.codebases,
            "expected_answer": e.expected_answer,
            "relevant": [{"target": t.label, "lines": list(t.lines or ())} for t in e.relevant],
            "expect_found": e.expect_found,
        }
        for e in container.evaluations.builtin()
    ]


# ---- observability ---------------------------------------------------------------------------


@router.get("/stats", tags=["observability"])
def stats(container: Container = Depends(get_container)) -> dict[str, Any]:
    return container.stats.stats()


@router.get("/health", tags=["observability"])
def health(container: Container = Depends(get_container)) -> dict[str, str]:
    return {
        "status": "ok",
        "models": container.models.status(),
        "reranker": _reranker_status(container),
        "samples": container.samples_status,
    }


def _reranker_status(container: Container) -> str:
    """ready · loading · disabled (RERANK_MODEL is empty) · unavailable (failed to load)."""
    reranker, reason = container.models.reranker()
    return "ready" if reranker is not None else (reason or "unavailable")


@router.get("/config", tags=["observability"])
def config(container: Container = Depends(get_container)) -> dict[str, Any]:
    """Limits, file rules and defaults, so a client can check input before sending it
    (FRONTEND_PLAN §9). Values come from the same settings and rules the server enforces."""
    s = container.settings
    reranker = _reranker_status(container)
    rerank_ok = reranker in ("ready", "loading")
    return {
        "limits": {
            "max_files_per_request": s.max_files_per_request,
            "max_bytes_per_request": s.max_bytes_per_request,
            "max_files_per_codebase": s.max_files_per_codebase,
            "max_bytes_per_codebase": s.max_bytes_per_codebase,
            "max_user_codebases": s.max_user_codebases,
            "codebase_ttl_hours": s.codebase_ttl_hours,
            "max_k": s.max_k,
            "question_max_chars": QUESTION_MAX_CHARS,
            "max_path_chars": MAX_PATH_CHARS,
            "minified_line_chars": MINIFIED_LINE_CHARS,
            "max_custom_examples": MAX_CUSTOM_EXAMPLES,
        },
        "files": {
            "extensions": sorted(EXTENSIONS),
            "extra_names": [".env.example"],
            "skipped_dirs": sorted(SKIPPED_DIRS),
            "lockfiles": sorted(LOCKFILES),
            "codebase_id_pattern": CODEBASE_ID_PATTERN,
        },
        "defaults": {"k": s.default_k, "mode": s.default_mode},
        "modes": [
            {
                "id": m.value,
                "available": m is not SearchMode.HYBRID_RERANK or rerank_ok,
                "reason": None
                if m is not SearchMode.HYBRID_RERANK or rerank_ok
                else f"The reranker is {reranker} on this server; this mode runs as hybrid.",
            }
            for m in SearchMode
        ],  # fmt: skip
        "pipeline_debug": s.pipeline_debug_enabled,
        "rate_limits": {
            "query_per_minute": s.rate_limit_query_per_minute,
            "query_per_day": s.rate_limit_query_per_day,
        },
    }
