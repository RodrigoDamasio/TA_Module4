import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    google_api_key: str | None
    gemini_model: str
    llm_mode: str  # gemini | fake
    llm_min_interval_s: float
    llm_timeout_s: int
    database_path: str
    chroma_path: str
    models_path: str
    embed_mode: str  # onnx | fake
    embed_model: str
    rerank_model: str  # "" = reranking disabled
    onnx_threads: int
    embed_batch_size: int
    chunk_max_chars: int
    chunk_overlap: float
    chunk_min_chars: int
    default_mode: str
    retrieval_candidates: int
    vector_weight: float
    bm25_weight: float
    default_k: int
    max_k: int
    rerank_max_chars: int
    context_budget_tokens: int
    max_files_per_request: int
    max_bytes_per_request: int
    max_files_per_codebase: int
    max_bytes_per_codebase: int
    max_user_codebases: int
    codebase_ttl_hours: int
    rate_limit_query_per_minute: int
    rate_limit_query_per_day: int
    rate_limit_index_per_minute: int
    rate_limit_index_per_day: int
    rate_limit_search_per_minute: int
    full_eval_max_calls: int
    max_queued_jobs: int
    sync_wait_timeout_s: int
    trace_retention: int
    pipeline_debug_enabled: bool
    llm_daily_request_limit: int
    price_input_per_m: float
    price_output_per_m: float
    runner_mode: str  # thread | inline (tests)
    base_url: str
    frontend_origins: list[str]

    @property
    def embedder_name(self) -> str:
        return self.embed_model if self.embed_mode == "onnx" else "fake-hashing-256"

    @property
    def llm_name(self) -> str:
        return self.gemini_model if self.llm_mode == "gemini" else "demo"


def get_settings() -> Settings:
    return Settings(
        google_api_key=os.getenv("GOOGLE_API_KEY") or None,
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
        llm_mode=os.getenv("LLM_MODE", "gemini"),
        llm_min_interval_s=_float("LLM_MIN_INTERVAL_S", 4.0),
        llm_timeout_s=_int("LLM_TIMEOUT_S", 90),
        database_path=os.getenv("DATABASE_PATH", "rag.db"),
        chroma_path=os.getenv("CHROMA_PATH", "chroma"),
        models_path=os.getenv("MODELS_PATH", "models"),
        embed_mode=os.getenv("EMBED_MODE", "onnx"),
        embed_model=os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5"),
        rerank_model=os.getenv("RERANK_MODEL", "Xenova/ms-marco-MiniLM-L-6-v2"),
        onnx_threads=_int("ONNX_THREADS", 2),
        embed_batch_size=_int("EMBED_BATCH_SIZE", 4),
        chunk_max_chars=_int("CHUNK_MAX_CHARS", 1400),
        chunk_overlap=_float("CHUNK_OVERLAP", 0.15),
        chunk_min_chars=_int("CHUNK_MIN_CHARS", 700),
        default_mode=os.getenv("DEFAULT_MODE", "hybrid"),
        retrieval_candidates=_int("RETRIEVAL_CANDIDATES", 20),
        vector_weight=_float("VECTOR_WEIGHT", 0.7),
        bm25_weight=_float("BM25_WEIGHT", 0.3),
        default_k=_int("DEFAULT_K", 5),
        max_k=_int("MAX_K", 10),
        rerank_max_chars=_int("RERANK_MAX_CHARS", 800),
        context_budget_tokens=_int("CONTEXT_BUDGET_TOKENS", 6000),
        max_files_per_request=_int("MAX_FILES_PER_REQUEST", 50),
        max_bytes_per_request=_int("MAX_BYTES_PER_REQUEST", 500_000),
        max_files_per_codebase=_int("MAX_FILES_PER_CODEBASE", 200),
        max_bytes_per_codebase=_int("MAX_BYTES_PER_CODEBASE", 1_000_000),
        max_user_codebases=_int("MAX_USER_CODEBASES", 10),
        codebase_ttl_hours=_int("CODEBASE_TTL_HOURS", 24),
        rate_limit_query_per_minute=_int("RATE_LIMIT_QUERY_PER_MINUTE", 10),
        rate_limit_query_per_day=_int("RATE_LIMIT_QUERY_PER_DAY", 50),
        rate_limit_index_per_minute=_int("RATE_LIMIT_INDEX_PER_MINUTE", 5),
        rate_limit_index_per_day=_int("RATE_LIMIT_INDEX_PER_DAY", 20),
        rate_limit_search_per_minute=_int("RATE_LIMIT_SEARCH_PER_MINUTE", 30),
        full_eval_max_calls=_int("FULL_EVAL_MAX_CALLS", 0),
        max_queued_jobs=_int("MAX_QUEUED_JOBS", 5),
        sync_wait_timeout_s=_int("SYNC_WAIT_TIMEOUT_S", 180),
        trace_retention=_int("TRACE_RETENTION", 500),
        pipeline_debug_enabled=_bool("PIPELINE_DEBUG_ENABLED", True),
        llm_daily_request_limit=_int("LLM_DAILY_REQUEST_LIMIT", 1000),
        price_input_per_m=_float("PRICE_INPUT_PER_M", 0.10),
        price_output_per_m=_float("PRICE_OUTPUT_PER_M", 0.40),
        runner_mode=os.getenv("RUNNER_MODE", "thread"),
        base_url=os.getenv("BASE_URL", "http://localhost:8000").rstrip("/"),
        frontend_origins=[
            origin.strip().rstrip("/")
            for origin in os.getenv("FRONTEND_ORIGIN", "http://localhost:3000").split(",")
            if origin.strip()
        ],
    )
