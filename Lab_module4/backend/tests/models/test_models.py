"""Real ONNX models (M1–M4) and the retrieval regression (M3) — `pytest -m models`.

0 API calls: the models run locally (downloaded once to MODELS_PATH, ~150 MB)."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from app.application.embedding import CachedEmbeddings
from app.application.evaluation.evaluator import Evaluator, RunConfig
from app.application.evaluation.relevance import load_dataset, locate_in_content, resolve
from app.application.indexing import IndexingService, IndexLimits
from app.application.retrieval.bm25 import BM25Index
from app.application.retrieval.retriever import RetrievalSettings, Retriever
from app.application.tracing import Tracer
from app.chunking.registry import ChunkerRegistry
from app.domain.retrieval import SearchMode
from app.infrastructure.chroma_store import ChromaVectorStore
from app.infrastructure.fastembed_models import OnnxModels
from app.infrastructure.samples import (
    SAMPLES,
    ensure_samples,
    read_sample,
    sample_files,
    snapshot_path,
)
from app.infrastructure.sqlite_store import SqliteEmbeddingCache, SqliteIndexRepository

pytestmark = pytest.mark.models
BACKEND = Path(__file__).resolve().parents[2]
BASELINE = BACKEND / "eval" / "baseline.json"
EMBED = "BAAI/bge-small-en-v1.5"
RERANK = "Xenova/ms-marco-MiniLM-L-6-v2"
TOLERANCE = 0.02


@pytest.fixture(scope="module")
def models():
    loaded = OnnxModels(EMBED, RERANK, os.getenv("MODELS_PATH", str(BACKEND / "models")), 2, 4)
    loaded.start()
    assert loaded.wait_ready(900) and loaded.wait_all(900)
    return loaded


@pytest.fixture(scope="module")
def indexed(models):
    tmp = tempfile.mkdtemp()
    repo = SqliteIndexRepository(f"{tmp}/i.db")
    store = ChromaVectorStore(f"{tmp}/chroma", EMBED)
    bm25 = BM25Index()
    cache = CachedEmbeddings(SqliteEmbeddingCache(f"{tmp}/i.db"))
    indexing = IndexingService(repo, store, bm25, models, cache, ChunkerRegistry(),
                               IndexLimits())  # fmt: skip
    assert ensure_samples(indexing, repo, EMBED, embed_now=False) == "snapshot"
    return Retriever(store, bm25, models, cache, repo, RetrievalSettings()), store


# M1
def test_embedder_similarity_and_token_window(models):
    embedder = models.embedder()
    assert embedder.dim == 384 and embedder.max_tokens == 512
    query = embedder.embed_query("How are passwords hashed?")
    good, bad = embedder.embed_documents(
        ["def hash_password(p):\n    return bcrypt.hashpw(p, bcrypt.gensalt())",
         "export function computeBalance(entries) { return entries.length }"]  # fmt: skip
    )

    def cosine(a, b):
        return sum(x * y for x, y in zip(a, b, strict=True))

    assert cosine(query, good) > cosine(query, bad)
    longest = 0
    for codebase in SAMPLES:
        for file in sample_files(codebase):
            for chunk in ChunkerRegistry().chunk(codebase, file.path, file.content).chunks:
                longest = max(longest, embedder.count_tokens(chunk.embed_text))
    assert longest <= 512  # the 3-chars-per-token budget holds: nothing is truncated


# M2
def test_reranker_puts_the_relevant_chunk_first(models):
    reranker, reason = models.reranker()
    assert reason is None
    scores = reranker.score(
        "how does the payment client retry failed charges",
        ["def charge(self, amount, attempts=3):\n    for attempt in range(attempts): retry",
         "# Shopflow\nA small online shop."],  # fmt: skip
    )
    assert scores[0] > scores[1]


# M3 — retrieval regression (course "Level 4"): never worse than the stored baseline
def test_retrieval_does_not_regress(indexed):
    retriever, _ = indexed
    examples = resolve(
        load_dataset(BACKEND / "eval" / "dataset.json"),
        lambda cb, p: (lambda c: locate_in_content(p, c) if c else None)(read_sample(cb, p)),
    )
    current = {}
    for mode in (SearchMode.VECTOR, SearchMode.HYBRID, SearchMode.HYBRID_RERANK):
        report = Evaluator(retriever).retrieval(examples, RunConfig(5, mode, EMBED))
        overall = report["summary"]["retrieval"]["overall"]
        current[mode.value] = {"recall": overall["recall"], "mrr": overall["mrr"]}
    if os.getenv("UPDATE_BASELINE") == "1":
        BASELINE.write_text(json.dumps({"k": 5, "embedder": EMBED, "modes": current}, indent=1))
    baseline = json.loads(BASELINE.read_text())["modes"]
    for mode, metrics in baseline.items():
        for name, value in metrics.items():
            assert current[mode][name] >= value - TOLERANCE, (mode, name, current[mode], value)


# M4 — the committed snapshot is current and gives the same results as a fresh embed
def test_snapshot_matches_a_fresh_embed(models, indexed):
    assert snapshot_path(EMBED).is_file()
    retriever, store = indexed
    assert store.count() == sum(
        len(ChunkerRegistry().chunk(cb, f.path, f.content).chunks)
        for cb in SAMPLES
        for f in sample_files(cb)
    )
    tmp = tempfile.mkdtemp()
    repo = SqliteIndexRepository(f"{tmp}/i.db")
    fresh_store = ChromaVectorStore(f"{tmp}/chroma", EMBED)
    bm25 = BM25Index()
    cache = CachedEmbeddings(SqliteEmbeddingCache(f"{tmp}/i.db"))
    indexing = IndexingService(repo, fresh_store, bm25, models, cache, ChunkerRegistry(),
                               IndexLimits())  # fmt: skip
    assert ensure_samples(indexing, repo, EMBED, True, snapshot_dir=Path(tmp)) == "embedded"
    fresh = Retriever(fresh_store, bm25, models, cache, repo, RetrievalSettings())
    question = "Where is the database connection configured?"
    a = retriever.search(question, list(SAMPLES), 5, SearchMode.VECTOR, Tracer("s"))
    b = fresh.search(question, list(SAMPLES), 5, SearchMode.VECTOR, Tracer("s"))
    assert [h.chunk.id for h in a.hits] == [h.chunk.id for h in b.hits]
