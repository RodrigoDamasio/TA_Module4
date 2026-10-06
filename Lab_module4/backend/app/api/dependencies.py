"""Wiring: the only place that chooses concrete implementations. One Container per app
(tests build their own with temp storage, fake models and a fake LLM)."""

import gzip
import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Request

from app.application.answering import AnswerService, AnswerSettings
from app.application.budget import BudgetedLLMClient, CallBudget, RunCounter
from app.application.codebases import CodebaseService
from app.application.embedding import CachedEmbeddings, Models
from app.application.evaluation.evaluator import Evaluator, RunConfig
from app.application.evaluation.judge import LLMJudge
from app.application.evaluation.relevance import Located, locate_in_chunks, locate_in_content
from app.application.evaluation.service import EvaluationService
from app.application.indexing import IndexingService, IndexLimits
from app.application.jobs import JobService
from app.application.prompts import PromptLibrary
from app.application.retrieval.bm25 import BM25Index
from app.application.retrieval.retriever import RetrievalSettings, Retriever
from app.application.stats import MeteredLLMClient, Pricing, StatsService, UsageMeter
from app.application.structured import StructuredCaller
from app.chunking.registry import ChunkerRegistry
from app.config import Settings
from app.domain.ports import LLMClient, TraceStore
from app.domain.retrieval import SearchMode
from app.infrastructure.caching_llm import CachingLLMClient
from app.infrastructure.chroma_store import ChromaVectorStore
from app.infrastructure.demo_llm import DemoLLMClient
from app.infrastructure.fake_models import FakeModels
from app.infrastructure.fastembed_models import OnnxModels
from app.infrastructure.gemini_client import GeminiClient
from app.infrastructure.llm_decorators import (
    CircuitBreakerLLMClient,
    ConcurrencyLimitedLLMClient,
    PacedLLMClient,
    RetryingLLMClient,
)
from app.infrastructure.runner import InlineRunner, ThreadRunner
from app.infrastructure.samples import SNAPSHOT_DIR, ensure_samples, read_sample
from app.infrastructure.sqlite_store import (
    SqliteEmbeddingCache,
    SqliteIndexRepository,
    SqliteJobRepository,
    SqliteReportStore,
    SqliteResponseCache,
    SqliteTraceStore,
)

from .guards import RateLimiter

logger = logging.getLogger(__name__)
EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"
LLM_CACHE_SEED = SNAPSHOT_DIR / "llm_cache_seed.json.gz"


@dataclass
class Limiters:
    query: RateLimiter
    index: RateLimiter
    search: RateLimiter


@dataclass
class Container:
    settings: Settings
    models: Models
    indexing: IndexingService
    codebases: CodebaseService
    retriever: Retriever
    answers: AnswerService
    evaluations: EvaluationService
    jobs: JobService
    runner: InlineRunner | ThreadRunner
    stats: StatsService
    traces: TraceStore
    limiters: Limiters
    prompts: PromptLibrary
    response_cache: SqliteResponseCache
    breaker: CircuitBreakerLLMClient | None = None
    samples_status: str = "pending"
    _starter: threading.Thread | None = field(default=None, repr=False)

    def start(self) -> None:
        """Startup (§7.5): models, BM25 rebuild, repair, interrupted jobs, samples, cache
        seed, worker. Never blocks on the models: samples come from the snapshot."""
        if isinstance(self.models, OnnxModels):
            self.models.start()
        rebuilt = self.codebases.rebuild_keyword_index()
        repaired = self.codebases.reconcile()
        interrupted = self.jobs.recover()
        logger.info("startup bm25=%d repaired=%d interrupted=%d", rebuilt, len(repaired),
                    interrupted)  # fmt: skip
        self.seed_llm_cache()
        self.samples_status = self._ensure_samples(embed_now=self.models.status() == "ready")
        if self.samples_status == "pending":
            self._starter = threading.Thread(target=self._samples_later, daemon=True)
            self._starter.start()
        self.codebases.sweep_expired()
        self.runner.start()

    def stop(self) -> None:
        self.runner.stop()

    def _ensure_samples(self, embed_now: bool) -> str:
        return ensure_samples(
            self.indexing, self.indexing.repo, self.settings.embedder_name, embed_now
        )

    def _samples_later(self) -> None:
        self.samples_status = "indexing"
        if self.models.wait_ready(900):
            try:
                self.samples_status = self._ensure_samples(embed_now=True)
            except Exception:
                logger.exception("sample indexing failed")
                self.samples_status = "failed"
        else:
            self.samples_status = "failed"

    def seed_llm_cache(self) -> int:
        """Stored answers for the built-in evaluation (§9.4): production can replay the
        full evaluation at 0 calls."""
        if not LLM_CACHE_SEED.is_file():
            return 0
        with gzip.open(LLM_CACHE_SEED, "rt") as handle:
            return self.response_cache.seed(json.load(handle))

    def quota_status(self) -> dict:
        if self.breaker is None:
            return {"circuit": "closed", "mode": self.settings.llm_mode}
        try:
            self.breaker.ensure_closed()
        except Exception as err:  # LLMQuotaExceeded
            return {"circuit": "open", "retry_after_s": round(getattr(err, "retry_after_s", 0))}
        return {"circuit": "closed"}


def gemini_stack(settings: Settings) -> tuple[LLMClient, CircuitBreakerLLMClient]:
    """Uncached chain, outermost first: CircuitBreaker → Retrying → Gate → Paced → Gemini."""
    if not settings.google_api_key:
        raise RuntimeError("GOOGLE_API_KEY is not set (or use LLM_MODE=fake).")
    gemini = GeminiClient(settings.google_api_key, settings.gemini_model, settings.llm_timeout_s)
    gated = ConcurrencyLimitedLLMClient(
        PacedLLMClient(gemini, settings.llm_min_interval_s),
        limit=1,  # one free-tier quota: calls stay serialized
        wait_s=settings.llm_timeout_s * 3,
    )
    breaker = CircuitBreakerLLMClient(RetryingLLMClient(gated))
    return breaker, breaker


def build_container(
    settings: Settings, llm: LLMClient | None = None, models: Models | None = None
) -> Container:
    db = settings.database_path
    repo = SqliteIndexRepository(db)
    embedding_cache = SqliteEmbeddingCache(db)
    response_cache = SqliteResponseCache(db)
    traces = SqliteTraceStore(db, settings.trace_retention)
    if models is None:
        models = (
            FakeModels()
            if settings.embed_mode == "fake"
            else OnnxModels(
                settings.embed_model,
                settings.rerank_model,
                settings.models_path,
                settings.onnx_threads,
                settings.embed_batch_size,
            )
        )
    store = ChromaVectorStore(settings.chroma_path, settings.embedder_name)
    bm25 = BM25Index()
    embeddings = CachedEmbeddings(embedding_cache)
    limits = IndexLimits(
        settings.max_files_per_request,
        settings.max_bytes_per_request,
        settings.max_files_per_codebase,
        settings.max_bytes_per_codebase,
        settings.max_user_codebases,
        settings.codebase_ttl_hours,
    )
    chunkers = ChunkerRegistry(
        settings.chunk_max_chars, settings.chunk_overlap, settings.chunk_min_chars
    )
    indexing = IndexingService(repo, store, bm25, models, embeddings, chunkers, limits)
    codebases = CodebaseService(repo, store, bm25, indexing)
    retriever = Retriever(
        store,
        bm25,
        models,
        embeddings,
        repo,
        RetrievalSettings(
            settings.retrieval_candidates,
            settings.rerank_max_chars,
            settings.vector_weight,
            settings.bm25_weight,
        ),
    )

    breaker = None
    if llm is not None:
        base = llm
    elif settings.llm_mode == "fake":
        base = DemoLLMClient()
    else:
        base, breaker = gemini_stack(settings)
    meter = UsageMeter()
    model = settings.llm_name
    prompts = PromptLibrary()
    answer_settings = AnswerSettings(settings.context_budget_tokens)
    live = MeteredLLMClient(CachingLLMClient(base, response_cache, model), meter)
    answers = AnswerService(
        retriever, StructuredCaller(live, prompts, model), prompts, answer_settings
    )

    def full_evaluator(max_calls: int) -> tuple[Evaluator, CallBudget]:
        budget = CallBudget(max_calls)
        cached = CachingLLMClient(BudgetedLLMClient(base, budget), response_cache, model)
        caller = StructuredCaller(MeteredLLMClient(RunCounter(cached, budget), meter), prompts,
                                  model)  # fmt: skip
        run_answers = AnswerService(retriever, caller, prompts, answer_settings)
        return Evaluator(retriever, run_answers, LLMJudge(caller, prompts), budget), budget

    def locate(codebase: str, path: str) -> Located | None:
        content = read_sample(codebase, path)
        if content is not None:
            return locate_in_content(path, content)
        chunks = list(store.iter_chunks(codebase, path))
        return locate_in_chunks(chunks) if chunks else None

    evaluations = EvaluationService(
        Evaluator(retriever),
        full_evaluator,
        SqliteReportStore(db),
        locate,
        EVAL_DIR / "dataset.json",
        EVAL_DIR / "bad_answers.json",
        EVAL_DIR / "results",
        RunConfig(
            settings.default_k,
            SearchMode(settings.default_mode),
            settings.embedder_name,
            prompts.version,
            model,
        ),  # fmt: skip
        settings.full_eval_max_calls,
    )
    jobs = JobService(SqliteJobRepository(db), indexing, models, evaluations.run_full_job)
    runner: InlineRunner | ThreadRunner = (
        InlineRunner(jobs.run)
        if settings.runner_mode == "inline"
        else ThreadRunner(jobs.run, settings.max_queued_jobs, codebases.sweep_expired)
    )
    jobs.runner = runner

    def index_totals() -> dict[str, int]:
        all_codebases = repo.list_codebases()
        return {
            "codebases": len(all_codebases),
            "chunks": sum(c.chunk_count for c in all_codebases),
            "files": sum(c.file_count for c in all_codebases),
        }

    container = Container(
        settings=settings,
        models=models,
        indexing=indexing,
        codebases=codebases,
        retriever=retriever,
        answers=answers,
        evaluations=evaluations,
        jobs=jobs,
        runner=runner,
        stats=None,  # type: ignore[arg-type] — set below (needs the container's quota view)
        traces=traces,
        limiters=Limiters(
            query=RateLimiter(
                settings.rate_limit_query_per_minute, settings.rate_limit_query_per_day
            ),  # fmt: skip
            index=RateLimiter(
                settings.rate_limit_index_per_minute, settings.rate_limit_index_per_day
            ),  # fmt: skip
            search=RateLimiter(settings.rate_limit_search_per_minute, 10**6),
        ),
        prompts=prompts,
        response_cache=response_cache,
        breaker=breaker,
    )
    container.stats = StatsService(
        traces,
        meter,
        embedding_cache,
        index_totals,
        container.quota_status,
        Pricing(
            settings.llm_daily_request_limit,
            settings.price_input_per_m,
            settings.price_output_per_m,
        ),
        settings.trace_retention,
    )
    return container


def get_container(request: Request) -> Container:
    return request.app.state.container
