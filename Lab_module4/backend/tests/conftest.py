import dataclasses
import time
from pathlib import Path

import pytest
from fakes import FakeLLM

from app.application.answering import AnswerService, AnswerSettings
from app.application.codebases import CodebaseService
from app.application.embedding import CachedEmbeddings
from app.application.indexing import IndexingService, IndexLimits
from app.application.prompts import PromptLibrary
from app.application.retrieval.bm25 import BM25Index
from app.application.retrieval.retriever import RetrievalSettings, Retriever
from app.application.structured import StructuredCaller
from app.chunking.registry import ChunkerRegistry
from app.config import get_settings
from app.domain.codebases import CodebaseKind
from app.domain.files import SourceFile
from app.infrastructure.chroma_store import ChromaVectorStore
from app.infrastructure.fake_models import FakeModels, HashingEmbedder
from app.infrastructure.samples import SAMPLES, sample_files
from app.infrastructure.sqlite_store import SqliteEmbeddingCache, SqliteIndexRepository

ROOT = Path(__file__).resolve().parents[1]


@dataclasses.dataclass
class Stack:
    """The real application services over temp storage, fake models and a fake LLM."""

    repo: SqliteIndexRepository
    store: ChromaVectorStore
    bm25: BM25Index
    models: FakeModels
    embedder: HashingEmbedder
    cache: SqliteEmbeddingCache
    indexing: IndexingService
    codebases: CodebaseService
    retriever: Retriever
    answers: AnswerService
    llm: FakeLLM
    prompts: PromptLibrary

    def index(self, codebase: str, files: dict[str, str], kind=CodebaseKind.USER) -> dict:
        return self.indexing.index(codebase, [SourceFile(p, c) for p, c in files.items()], kind)

    def index_samples(self) -> None:
        for codebase in SAMPLES:
            self.indexing.index(codebase, sample_files(codebase), CodebaseKind.SAMPLE)


def make_stack(
    tmp_path: Path,
    llm: FakeLLM | None = None,
    limits: IndexLimits | None = None,
    min_chars: int = 700,
    **models,
) -> Stack:
    tmp_path.mkdir(parents=True, exist_ok=True)
    db = str(tmp_path / "rag.db")
    repo, cache = SqliteIndexRepository(db), SqliteEmbeddingCache(db)
    embedder = HashingEmbedder()
    fake_models = FakeModels(embedder=embedder, **models)
    store = ChromaVectorStore(str(tmp_path / "chroma"), embedder.name)
    bm25 = BM25Index()
    embeddings = CachedEmbeddings(cache)
    indexing = IndexingService(
        repo,
        store,
        bm25,
        fake_models,
        embeddings,
        ChunkerRegistry(min_chars=min_chars),
        limits or IndexLimits(),
    )
    retriever = Retriever(store, bm25, fake_models, embeddings, repo, RetrievalSettings())
    llm = llm or FakeLLM()
    prompts = PromptLibrary()
    answers = AnswerService(
        retriever, StructuredCaller(llm, prompts, "fake"), prompts, AnswerSettings()
    )
    return Stack(
        repo, store, bm25, fake_models, embedder, cache, indexing,
        CodebaseService(repo, store, bm25, indexing), retriever, answers, llm, prompts,
    )  # fmt: skip


@pytest.fixture
def stack(tmp_path):
    def make(**kwargs) -> Stack:
        return make_stack(tmp_path / f"s{time.monotonic_ns()}", **kwargs)

    return make


@pytest.fixture(scope="session")
def samples_stack(tmp_path_factory) -> Stack:
    """Both samples indexed once (read-only use)."""
    s = make_stack(tmp_path_factory.mktemp("samples"))
    s.index_samples()
    return s


# ---- API (fake LLM + fake models, temp storage) -------------------------------------------

API_SETTINGS = {
    "llm_mode": "fake",
    "embed_mode": "fake",
    "runner_mode": "inline",
    "rate_limit_query_per_minute": 1000,
    "rate_limit_query_per_day": 10_000,
    "rate_limit_index_per_minute": 1000,
    "rate_limit_index_per_day": 10_000,
    "rate_limit_search_per_minute": 1000,
    "full_eval_max_calls": 100,
}


class Api:
    def __init__(self, client, container, llm: FakeLLM) -> None:
        self.client, self.container, self.llm = client, container, llm

    def query(self, question: str, codebases=("shopflow",), **extra):
        return self.client.post(
            "/query", json={"question": question, "codebases": list(codebases), **extra}
        )


@pytest.fixture
def api(tmp_path):
    from fastapi.testclient import TestClient

    from app.api.dependencies import build_container
    from app.main import create_app

    clients = []

    def make(llm: FakeLLM | None = None, raise_errors: bool = True, **settings) -> Api:
        llm = llm or FakeLLM()
        folder = tmp_path / f"api{len(clients)}"
        s = dataclasses.replace(
            get_settings(),
            **(
                API_SETTINGS
                | {
                    "database_path": str(folder / "api.db"),
                    "chroma_path": str(folder / "chroma"),
                }
                | settings
            ),
        )
        container = build_container(s, llm=llm)
        client = TestClient(
            create_app(s, container), raise_server_exceptions=raise_errors
        ).__enter__()
        clients.append(client)
        return Api(client, container, llm)

    yield make
    for client in clients:
        client.__exit__(None, None, None)
