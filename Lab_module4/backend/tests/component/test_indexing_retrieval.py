"""Indexing, caches, codebases (I1–I8) and the search modes (R4–R5): real ChromaDB in a temp
dir, fake embedder and reranker, 0 calls."""

from datetime import UTC, datetime, timedelta

import pytest

from app.application.indexing import IndexLimits
from app.application.tracing import Tracer
from app.domain.chunks import CHUNKER_VERSION
from app.domain.codebases import CodebaseKind
from app.domain.errors import (
    CodebaseNotFound,
    EmptyIndex,
    InputTooLarge,
    InvalidPath,
    ReadOnlyCodebase,
    TooManyCodebases,
    UnsupportedFileType,
)
from app.domain.files import SourceFile
from app.domain.retrieval import SearchMode
from app.infrastructure.samples import ensure_samples, samples_current

FILES = {
    "app/auth.py": "def login(email, password):\n    return create_token(email)\n",
    "app/orders.py": "def place_order(cart):\n    return charge(cart.total)\n",
    "README.md": "# Demo\n\nA demo project about orders and login.\n",
}


# I1
def test_first_index_writes_vectors_keyword_index_and_records(stack):
    s = stack()
    updates = []
    result = s.indexing.index("demo", [SourceFile(p, c) for p, c in FILES.items()],
                              progress=updates.append)  # fmt: skip
    assert result["files_indexed"] == 3 and result["chunks_added"] == s.store.count() == 3
    assert result["by_language"] == {"python": 2, "markdown": 1}
    assert len(s.bm25) == 3 and updates[-1]["files_done"] == 3
    codebase = s.repo.get_codebase("demo")
    assert (codebase.file_count, codebase.chunk_count, codebase.kind) == (3, 3, CodebaseKind.USER)
    assert codebase.expires_at is not None
    record = s.repo.get_file("demo", "app/auth.py")
    assert record.chunker_version == CHUNKER_VERSION and record.chunk_count == 1


# I2
def test_reindexing_unchanged_files_does_nothing(stack):
    s = stack()
    s.index("demo", FILES)
    calls = s.embedder.calls
    again = s.index("demo", FILES)
    assert again["files_unchanged"] == 3 and again["files_indexed"] == 0
    assert s.embedder.calls == calls


# I3
def test_changed_file_replaces_only_its_chunks_everywhere(stack):
    s = stack(min_chars=0)
    s.index("demo", FILES)
    changed = {"app/auth.py": "def login(email):\n    return 1\n\n\ndef logout():\n    return 2\n"}
    result = s.index("demo", changed)
    assert (result["files_indexed"], result["chunks_added"], result["chunks_removed"]) == (1, 2, 1)
    stored = [c.symbol for c in s.store.iter_chunks("demo", "app/auth.py")]
    assert sorted(stored) == ["login", "logout"] and s.store.count("demo") == 4
    assert len(s.bm25) == 4
    assert not s.bm25.search("create_token", ["demo"], 5)  # old content gone from BM25 too


# I4
def test_embedding_cache_hits_across_codebases(stack):
    s = stack()
    s.index("one", FILES)
    calls = s.embedder.calls
    result = s.index("two", FILES)
    # same code, but the header names... the same path → identical embed text → cache hits
    assert result["embedding_cache_hits"] == 3 and s.embedder.calls == calls


# I5
def test_limits_and_read_only_samples(stack):
    s = stack(limits=IndexLimits(max_files_per_request=2, max_bytes_per_request=1000,
                                 max_files_per_codebase=3, max_user_codebases=1))  # fmt: skip
    files = [SourceFile(p, c) for p, c in FILES.items()]
    with pytest.raises(InputTooLarge, match="per request"):
        s.indexing.validate("demo", files)
    with pytest.raises(InputTooLarge, match="bytes per request"):
        s.indexing.validate("demo", [SourceFile("a.py", "x" * 1001)])
    with pytest.raises(InvalidPath):
        s.indexing.validate("Bad Name", files[:1])
    with pytest.raises(InvalidPath):
        s.indexing.validate("demo", [])
    with pytest.raises(InvalidPath):
        s.indexing.validate("demo", [files[0], files[0]])
    with pytest.raises(UnsupportedFileType):
        s.indexing.validate("demo", [SourceFile("a.exe", "x")])
    s.index("demo", dict(list(FILES.items())[:2]))
    with pytest.raises(InputTooLarge, match="at most 3 files"):
        s.indexing.validate("demo", [SourceFile("c.py", "x"), SourceFile("d.py", "y")])
    with pytest.raises(TooManyCodebases):
        s.indexing.validate("second", files[:1])
    s.index("sample", {"a.py": "x = 1\n"}, kind=CodebaseKind.SAMPLE)
    with pytest.raises(ReadOnlyCodebase):
        s.indexing.validate("sample", files[:1])
    with pytest.raises(ReadOnlyCodebase):
        s.codebases.delete("sample")


# I6
def test_crash_between_vector_store_and_records_is_repaired(stack):
    s = stack()
    s.index("demo", FILES)
    s.repo.delete_file("demo", "app/auth.py")  # chunks written, record lost
    s.store.delete_file("demo", "app/orders.py")  # record says 1 chunk, store has 0
    repaired = s.codebases.reconcile()
    assert sorted(repaired) == ["demo/app/auth.py", "demo/app/orders.py"]
    assert s.store.count("demo") == 1 and s.repo.get_codebase("demo").file_count == 1
    assert s.index("demo", FILES)["files_indexed"] == 2  # the next index redoes both
    assert s.codebases.reconcile() == []


# I7
def test_expiry_sweeper_deletes_only_expired_user_codebases(stack):
    s = stack()
    s.index("old", FILES)
    s.index("sample", {"a.py": "x = 1\n"}, kind=CodebaseKind.SAMPLE)
    s.codebases._clock = lambda: datetime.now(UTC) + timedelta(hours=25)
    assert s.codebases.sweep_expired() == ["old"]
    assert s.store.count("old") == 0 and s.repo.get_codebase("old") is None
    assert not s.bm25.search("login", ["old"], 5)
    assert s.repo.get_codebase("sample") is not None


# I8
def test_startup_rebuild_and_sample_loading(stack, tmp_path):
    s = stack()
    assert not samples_current(s.repo)
    assert ensure_samples(s.indexing, s.repo, "no-snapshot-model", embed_now=False) == "pending"
    assert ensure_samples(s.indexing, s.repo, "no-snapshot-model", embed_now=True) == "embedded"
    assert samples_current(s.repo)
    assert ensure_samples(s.indexing, s.repo, "x", embed_now=True) == "current"
    total = s.store.count()
    s.bm25.remove_codebase("shopflow")
    s.bm25.remove_codebase("ledger")
    assert s.codebases.rebuild_keyword_index() == total == len(s.bm25)
    assert [c.id for c in s.codebases.all()] == ["ledger", "shopflow"]
    with pytest.raises(CodebaseNotFound):
        s.codebases.get("nope")
    chunks = s.codebases.chunks("shopflow", "backend/app/db.py")
    assert chunks[0].start_line == 1 and "create_db_engine" in chunks[0].symbol
    assert [f.path for f in s.codebases.files("ledger")][0] == "README.md"


# R4
@pytest.mark.parametrize("mode", list(SearchMode))
def test_every_mode_returns_sorted_hits_with_their_scores(samples_stack, mode):
    tracer = Tracer("search")
    result = samples_stack.retriever.search("processOrder cart", ["shopflow"], 5, mode, tracer)
    hits = result.hits
    assert 0 < len(hits) <= 5 and [h.rank for h in hits] == list(range(1, len(hits) + 1))
    assert all(h.chunk.codebase == "shopflow" for h in hits)
    top = hits[0].scores
    if mode is SearchMode.VECTOR:
        assert top.vector is not None and top.rrf is None and result.debug.bm25 == []
    if mode is SearchMode.BM25:
        assert top.bm25 is not None and result.debug.vector == []
        assert [h.scores.bm25 for h in hits] == sorted([h.scores.bm25 for h in hits], reverse=True)
    if mode is SearchMode.HYBRID:
        assert top.rrf is not None and result.debug.rerank_skipped == "mode=hybrid"
    if mode is SearchMode.HYBRID_RERANK:
        reranked = [h.scores.rerank for h in hits]
        assert reranked == sorted(reranked, reverse=True)
        assert [c.chunk_id for c in result.debug.reranked] == [h.chunk.id for h in hits]
    names = [s.name for s in tracer.spans]
    assert ("bm25" in names) == (mode is not SearchMode.VECTOR)
    assert ("rerank" in names) == (mode is SearchMode.HYBRID_RERANK)


def test_codebase_filter_and_errors(samples_stack, stack):
    tracer = Tracer("search")
    both = samples_stack.retriever.search("authentication api key token", ["shopflow", "ledger"],
                                          20, SearchMode.HYBRID, tracer)  # fmt: skip
    assert {h.chunk.codebase for h in both.hits} == {"shopflow", "ledger"}
    only = samples_stack.retriever.search("authentication api key token", ["ledger"], 20,
                                          SearchMode.HYBRID, tracer)  # fmt: skip
    assert {h.chunk.codebase for h in only.hits} == {"ledger"}
    with pytest.raises(CodebaseNotFound):
        samples_stack.retriever.search("x y", ["nope"], 5, SearchMode.VECTOR, tracer)
    empty = stack()
    empty.indexing.ensure_codebase("blank", CodebaseKind.USER)
    with pytest.raises(EmptyIndex):
        empty.retriever.search("x y", ["blank"], 5, SearchMode.VECTOR, tracer)


# R5
def test_rerank_disabled_falls_back_to_hybrid(stack):
    s = stack(rerank_disabled=True)
    s.index("demo", FILES)
    result = s.retriever.search("login", ["demo"], 3, SearchMode.HYBRID_RERANK, Tracer("s"))
    assert result.mode is SearchMode.HYBRID and result.debug.rerank_skipped == "disabled"
    assert all(h.scores.rerank is None for h in result.hits)
