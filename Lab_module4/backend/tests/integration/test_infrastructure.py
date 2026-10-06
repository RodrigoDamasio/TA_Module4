"""Adapters: ChromaDB (I9), SQLite stores (Q3), LLM cache + Gemini adapter + decorators
(Q1, Lab 3), runner, ONNX model loader, sample snapshot (M4 with the fake embedder)."""

import gzip
import json
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fakes import FakeLLM
from google.genai import errors, types

from app.application.stats import UsageMeter
from app.application.tracing import Tracer
from app.chunking.registry import ChunkerRegistry
from app.domain.chunks import CHUNKER_VERSION, Chunk
from app.domain.codebases import Codebase, CodebaseKind
from app.domain.errors import (
    EvaluationNotFound,
    JobNotFound,
    LLMOverloaded,
    LLMQuotaExceeded,
    LLMUnavailable,
    ModelsLoading,
    QueueFull,
)
from app.domain.jobs import Job
from app.domain.ports import (
    AssistantMessage,
    LLMRequest,
    LLMResponse,
    TokenUsage,
    ToolCall,
    ToolResult,
    ToolResultsMessage,
    UserMessage,
)
from app.domain.retrieval import SearchMode
from app.domain.schemas import AnswerLLM
from app.infrastructure.caching_llm import CachingLLMClient, request_key
from app.infrastructure.chroma_store import ChromaVectorStore, collection_name
from app.infrastructure.demo_llm import DemoLLMClient
from app.infrastructure.fake_models import HashingEmbedder
from app.infrastructure.fastembed_models import FastEmbedEmbedder, FastEmbedReranker, OnnxModels
from app.infrastructure.gemini_client import quota_error, to_contents, to_response
from app.infrastructure.llm_decorators import (
    CircuitBreakerLLMClient,
    ConcurrencyLimitedLLMClient,
    PacedLLMClient,
    RetryingLLMClient,
)
from app.infrastructure.runner import InlineRunner, ThreadRunner
from app.infrastructure.samples import (
    SAMPLES,
    build_snapshot,
    ensure_samples,
    read_sample,
    sample_files,
    samples_current,
    snapshot_path,
)
from app.infrastructure.sqlite_store import (
    SqliteEmbeddingCache,
    SqliteJobRepository,
    SqliteReportStore,
    SqliteResponseCache,
    SqliteTraceStore,
)

REQ = LLMRequest("sys", [UserMessage("hi")], response_schema=AnswerLLM)


def chunks_for(codebase: str, path: str, source: str) -> list[Chunk]:
    return ChunkerRegistry(min_chars=0).chunk(codebase, path, source).chunks


# I9
def test_chroma_adapter_round_trip_filters_and_deletes(tmp_path):
    store = ChromaVectorStore(str(tmp_path / "chroma"), "BAAI/bge-small-en-v1.5")
    embedder = HashingEmbedder()
    a = chunks_for("a", "x.py", "class A:\n    pass\n\n\ndef f(x):\n    return x\n")
    b = chunks_for("b", "y.py", "def g():\n    return 2\n")
    store.upsert(a + b, embedder.embed_documents([c.embed_text for c in a + b]))
    store.upsert([], [])
    assert store.count() == 3 and store.count("a") == 2
    got = {c.id: c for c in store.get([c.id for c in a])}
    assert got[a[0].id] == a[0]  # metadata round trip (part, signature, header, None-free)
    near = store.query(embedder.embed_query("def g return"), ["b"], 10)
    assert [i for i, _ in near] == [b[0].id] and 0 <= near[0][1] <= 2
    both = store.query(embedder.embed_query("f"), ["a", "b"], 10)
    assert {i for i, _ in both} == {c.id for c in a + b}
    assert store.query([0.1] * 256, [], 5) == []
    assert [c.path for c in store.iter_chunks("a", "x.py")] == ["x.py", "x.py"]
    assert store.delete_file("a", "x.py") == 2 and store.delete_file("a", "x.py") == 0
    assert store.delete_codebase("b") == 1 and store.count() == 0
    assert store.query(embedder.embed_query("g"), ["b"], 5) == [] and store.get([]) == []
    reopened = ChromaVectorStore(str(tmp_path / "chroma"), "BAAI/bge-small-en-v1.5")
    assert reopened.count() == 0
    assert collection_name("BAAI/bge-small-en-v1.5") == "chunks-baai-bge-small-en-v1-5"


def test_chroma_iterates_in_pages(tmp_path, monkeypatch):
    import app.infrastructure.chroma_store as module

    monkeypatch.setattr(module, "PAGE", 2)
    store = ChromaVectorStore(str(tmp_path / "chroma"), "m")
    source = "".join(f"def f{i}():\n    return {i}\n\n\n" for i in range(5))
    chunks = chunks_for("a", "x.py", source)
    store.upsert(chunks, HashingEmbedder().embed_documents([c.embed_text for c in chunks]))
    assert len(list(store.iter_chunks())) == 5


# Q3 and the SQLite adapters
def test_sqlite_stores(tmp_path):
    db = str(tmp_path / "s.db")
    cache = SqliteEmbeddingCache(db)
    cache.put_many("m", {"k1": [0.5, -1.25]})
    assert cache.get_many("m", ["k1", "k2"]) == {"k1": [0.5, -1.25]}
    assert cache.get_many("other", ["k1"]) == {}
    assert cache.stats() == {"stored": 1, "hits": 1, "misses": 2}

    traces = SqliteTraceStore(db, retention=3)
    for n in range(5):
        tracer = Tracer("query", f"req_{n}")
        with tracer.span("generate") as s:
            s["cached"] = n % 2 == 0
        traces.save(tracer.finish(found=True))
    recent = traces.recent(10)
    assert [t.request_id for t in recent] == ["req_4", "req_3", "req_2"]  # pruned to 3
    assert recent[0].spans[0].attrs == {"cached": True} and recent[0].attrs["found"] is True

    jobs = SqliteJobRepository(db)
    job = Job.create("index", {"codebase": "x"})
    jobs.save(job)
    assert jobs.get(job.id).request == {"codebase": "x"}
    assert [j.id for j in jobs.with_status({"queued"})] == [job.id]
    with pytest.raises(JobNotFound):
        jobs.get("' OR '1'='1")  # bound parameter, not SQL

    reports = SqliteReportStore(db)
    reports.save("r1", "retrieval", {"kind": "retrieval", "summary": {"x": 1}})
    assert reports.get("r1")["summary"] == {"x": 1}
    assert reports.all()[0] | {"created_at": None} == {
        "id": "r1", "kind": "retrieval", "created_at": None, "summary": {"x": 1}}  # fmt: skip
    with pytest.raises(EvaluationNotFound):
        reports.get("nope")

    responses = SqliteResponseCache(db)
    assert responses.seed({"a": {"text": "x"}}) == 1 and responses.export() == {"a": {"text": "x"}}


# Q1 (Lab 3)
def test_identical_request_is_served_from_cache(tmp_path):
    llm = FakeLLM()
    cache = CachingLLMClient(llm, SqliteResponseCache(str(tmp_path / "m.db")), "m1")
    first, second = cache.generate(REQ), cache.generate(REQ)
    assert len(llm.requests) == 1 and not first.cached and second.cached
    assert second.parsed == first.parsed
    CachingLLMClient(llm, SqliteResponseCache(str(tmp_path / "m.db")), "m2").generate(REQ)
    assert len(llm.requests) == 2
    assert request_key("m1", REQ) != request_key(
        "m1", LLMRequest("sys", [UserMessage("hey")], response_schema=AnswerLLM)
    )

    class Truncated:
        def generate(self, request):
            return LLMResponse("{", [], None, TokenUsage(), "max_tokens")

    truncated = CachingLLMClient(Truncated(), SqliteResponseCache(str(tmp_path / "t.db")), "m")
    truncated.generate(REQ)
    assert not truncated.generate(REQ).cached  # never cache a cut-off answer


def test_gemini_adapter_mapping_and_recorded_responses():
    contents = to_contents(
        [
            UserMessage("task"),
            AssistantMessage(None, [ToolCall("c1", "read_file", {"path": "app.py"})]),
            ToolResultsMessage([ToolResult("c1", "read_file", "1│ x")]),
            AssistantMessage("notes", []),
        ]
    )
    assert [c.role for c in contents] == ["user", "model", "user", "model"]
    assert contents[1].parts[0].function_call.name == "read_file"
    cassette = sorted(Path(__file__).parents[1].joinpath("cassettes").glob("*.json"))[0]
    mapped = to_response(types.GenerateContentResponse.model_validate(json.loads(
        cassette.read_text())))  # fmt: skip
    assert mapped.tool_calls and mapped.usage.input > 0


def test_daily_quota_waits_for_the_real_reset():
    body = {"error": {"code": 429, "details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
         "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "12s"}]}}  # fmt: skip
    noon = datetime(2026, 10, 5, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    err = quota_error(errors.ClientError(429, body), now=noon)
    assert (err.scope, err.retry_after_s) == ("day", 43200)


class Clock:
    def __init__(self):
        self.now, self.slept = 1000.0, []

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.slept.append(s)
        self.now += s


def test_quota_decorators_and_gate():
    clock = Clock()
    paced = PacedLLMClient(FakeLLM(), 6, clock, clock.sleep)
    paced.generate(REQ)
    paced.generate(REQ)
    assert clock.slept == [6]
    inner = FakeLLM(fail={"AnswerLLM": LLMOverloaded("503")})
    with pytest.raises(LLMOverloaded):
        RetryingLLMClient(inner, sleep=clock.sleep).generate(REQ)
    assert len(inner.requests) == 3
    minute = FakeLLM(fail={"any": LLMQuotaExceeded("minute", 5)})
    with pytest.raises(LLMQuotaExceeded):
        RetryingLLMClient(minute, sleep=clock.sleep).generate(REQ)
    assert len(minute.requests) == 3
    breaker_inner = FakeLLM(fail={"any": LLMQuotaExceeded("day", 300)})
    breaker = CircuitBreakerLLMClient(breaker_inner, clock)
    for _ in range(2):
        with pytest.raises(LLMQuotaExceeded):
            breaker.generate(REQ)
    assert len(breaker_inner.requests) == 1

    gate = threading.Event()

    class Slow:
        def generate(self, request):
            gate.wait(2)
            return FakeLLM().generate(request)

    limited = ConcurrencyLimitedLLMClient(Slow(), limit=1, wait_s=0.05)
    worker = threading.Thread(target=limited.generate, args=(REQ,))
    worker.start()
    with pytest.raises(LLMUnavailable):
        limited.generate(REQ)
    gate.set()
    worker.join()


def test_usage_meter_rolls_over_at_midnight_pacific():
    day = {"d": datetime(2026, 10, 5, 23, 0, tzinfo=ZoneInfo("America/Los_Angeles"))}
    meter = UsageMeter(lambda: day["d"])
    meter.record(LLMResponse("x", [], None, TokenUsage(10, 5, 1), "stop"))
    meter.record(LLMResponse("x", [], None, TokenUsage(10, 5), "stop", cached=True))
    assert meter.snapshot() == {"real": 1, "cached": 1, "input_tokens": 10, "output_tokens": 6}
    day["d"] = datetime(2026, 10, 6, 0, 1, tzinfo=ZoneInfo("America/Los_Angeles"))
    assert meter.snapshot()["real"] == 0


def test_runners():
    done = []
    inline = InlineRunner(done.append)
    inline.start()
    inline.submit("a")
    assert done == ["a"] and inline.has_capacity()
    inline.stop()

    seen, swept = [], threading.Event()

    def run(job_id):
        if job_id == "boom":
            raise RuntimeError("crash")
        seen.append(job_id)

    runner = ThreadRunner(run, max_queued=5, sweep=swept.set, sweep_every_s=0.01)
    runner.start()
    for job_id in ("boom", "b", "c"):
        runner.submit(job_id)
    deadline = time.monotonic() + 5
    while seen != ["b", "c"] and time.monotonic() < deadline:
        time.sleep(0.01)
    assert seen == ["b", "c"] and swept.wait(2)  # a crash never kills the worker
    runner.stop()
    full = ThreadRunner(run, max_queued=1)
    full.submit("x")
    assert not full.has_capacity()
    with pytest.raises(QueueFull):
        full.submit("y")
    full.stop()  # queue full: stop still returns


def test_onnx_models_load_in_the_background_with_a_stub_loader():
    release = threading.Event()

    def loader(kind):
        release.wait(2)
        if kind == "reranker":
            raise RuntimeError("download failed")
        return HashingEmbedder()

    models = OnnxModels("e", "r", "dir", 1, 4, loader=loader)
    with pytest.raises(ModelsLoading):
        models.embedder()
    assert models.status() == "loading" and models.reranker() == (None, "loading")
    models.start()
    release.set()
    assert models.wait_ready(2) and models.wait_all(2)
    assert models.status() == "ready" and models.embedder().dim == 256
    assert models.reranker() == (None, "unavailable")
    disabled = OnnxModels("e", "", "dir", 1, 4, loader=lambda kind: HashingEmbedder())
    assert disabled.reranker() == (None, "disabled")

    def broken(kind):
        raise RuntimeError("no model")

    failed = OnnxModels("e", "r", "dir", 1, 4, loader=broken)
    failed.start()
    failed.wait_all(2)
    assert failed.status() == "failed"


def test_fastembed_adapters_with_stub_models():
    class Vector(list):
        def tolist(self):
            return list(self)

    class StubModel:
        def query_embed(self, texts):
            return iter([Vector([0.1, 0.2, 0.3]) for _ in texts])

        def embed(self, texts, batch_size):
            assert batch_size == 4
            return iter([Vector([1.0, 0.0, 0.0]) for _ in texts])

        def rerank(self, query, texts, batch_size):
            return [float(len(t)) for t in texts]

    embedder = FastEmbedEmbedder(StubModel(), "BAAI/bge-small-en-v1.5", 4)
    assert (embedder.dim, embedder.max_tokens) == (3, 512)
    assert embedder.embed_documents(["a", "b"]) == [[1.0, 0.0, 0.0]] * 2
    assert embedder.embed_documents([]) == [] and embedder.embed_query("q") == [0.1, 0.2, 0.3]
    reranker = FastEmbedReranker(StubModel(), "r")
    assert reranker.score("q", ["ab", "a"]) == [2.0, 1.0] and reranker.score("q", []) == []


# M4 (fake embedder) — the snapshot gives the same index as a fresh embed
def test_snapshot_round_trip_and_staleness(stack, tmp_path):
    embedder = HashingEmbedder()
    path = snapshot_path(embedder.name, tmp_path)
    expected = sum(
        len(ChunkerRegistry().chunk(cb, f.path, f.content).chunks)
        for cb in SAMPLES
        for f in sample_files(cb)
    )
    assert build_snapshot(embedder, ChunkerRegistry(), path) == expected
    fresh, loaded = stack(), stack()
    fresh.index_samples()
    how = ensure_samples(loaded.indexing, loaded.repo, embedder.name, False, snapshot_dir=tmp_path)
    assert how == "snapshot"
    assert samples_current(loaded.repo)
    for s in (fresh, loaded):
        assert s.store.count() == expected and len(s.bm25) == expected
    query = "Where is the database connection configured?"
    a = fresh.retriever.search(query, list(SAMPLES), 5, SearchMode.HYBRID, Tracer("s"))
    b = loaded.retriever.search(query, list(SAMPLES), 5, SearchMode.HYBRID, Tracer("s"))
    assert [h.chunk.id for h in a.hits] == [h.chunk.id for h in b.hits]
    codebase = loaded.repo.get_codebase("shopflow")
    assert codebase.kind is CodebaseKind.SAMPLE and 0 < codebase.chunk_count < expected
    # a stale snapshot (other model) is refused, so the samples are embedded instead
    other = stack()
    how = ensure_samples(other.indexing, other.repo, "other-model", True, snapshot_dir=tmp_path)
    assert how == "embedded"
    with gzip.open(path, "rt") as handle:
        first = json.loads(handle.readline())
    assert first["chunker_version"] == CHUNKER_VERSION and len(first["vectors"][0]) == 256


def test_read_sample_refuses_unknown_codebases_and_escapes():
    assert read_sample("shopflow", "README.md").startswith("# Shopflow")
    assert read_sample("shopflow", "../ledger/README.md") is None
    assert read_sample("other", "README.md") is None
    assert read_sample("shopflow", "nope.md") is None


def test_demo_llm_cites_the_top_excerpts():
    from app.application.prompts import PromptLibrary

    user = PromptLibrary().answer_task("q", "[1] shopflow/a.py:1-2 · f\n````python\nx\n````")
    response = DemoLLMClient().generate(LLMRequest("s", [UserMessage(user)],
                                                   response_schema=AnswerLLM))  # fmt: skip
    assert response.parsed["citations"] == [1] and "`f` [1]" in response.parsed["answer"]
    empty = DemoLLMClient().generate(LLMRequest("s", [UserMessage("# Code excerpts\n")],
                                                response_schema=AnswerLLM))  # fmt: skip
    assert empty.parsed["found"] is False
    assert DemoLLMClient().generate(LLMRequest("s", [UserMessage("x")])).parsed == {
        "text": "Demo mode."}  # fmt: skip


def test_codebase_view_shape():
    from app.api.schemas import codebase_view

    view = codebase_view(Codebase("x", CodebaseKind.USER, "t", "t", "e"))
    assert view["read_only"] is False and view["expires_at"] == "e"
