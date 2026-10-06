"""Comparison grid (§9.3): chunking strategy × search mode × K × embedder — 0 API calls.

Each configuration gets its own temporary index (ChromaDB + BM25) built from the sample
files; the persistent embedding cache makes repeated runs fast. Writes
eval/results/grid.json and prints a Markdown table for EVALUATION.md.

    python -m eval.grid
    python -m eval.grid --embedders BAAI/bge-small-en-v1.5   # one embedder only
"""

import argparse
import json
import tempfile
import time

from app.application.embedding import CachedEmbeddings
from app.application.evaluation.evaluator import RETRIEVAL_METRICS, retrieval_row, summarize
from app.application.evaluation.metrics import percentile
from app.application.evaluation.relevance import load_dataset, locate_in_content, resolve
from app.application.indexing import IndexingService, IndexLimits
from app.application.retrieval.bm25 import BM25Index
from app.application.retrieval.retriever import RetrievalSettings, Retriever
from app.application.tracing import Tracer
from app.chunking.registry import ChunkerRegistry, Strategy
from app.domain.codebases import CodebaseKind
from app.domain.retrieval import SearchMode
from app.infrastructure.chroma_store import ChromaVectorStore
from app.infrastructure.samples import SAMPLES, read_sample, sample_files
from app.infrastructure.sqlite_store import SqliteEmbeddingCache, SqliteIndexRepository

from .common import EVAL_DB, EVAL_DIR, RESULTS, eval_settings, load_models

EMBEDDERS = ("BAAI/bge-small-en-v1.5", "sentence-transformers/all-MiniLM-L6-v2")
KS = (3, 5, 10)
FIXED_CHARS = 500  # the course's fixed-size baseline (chunk_size=500, §2.2)


def run(embedders: list[str]) -> dict:
    examples = resolve(
        load_dataset(EVAL_DIR / "dataset.json"),
        lambda cb, p: (lambda c: locate_in_content(p, c) if c is not None else None)(
            read_sample(cb, p)
        ),
    )
    cache = CachedEmbeddings(SqliteEmbeddingCache(str(EVAL_DB)))
    rows = []
    for embed_model in embedders:
        settings = eval_settings(embed_model=embed_model)
        models = load_models(settings)
        for strategy in Strategy:
            with tempfile.TemporaryDirectory() as tmp:
                repo = SqliteIndexRepository(f"{tmp}/index.db")
                store = ChromaVectorStore(f"{tmp}/chroma", embed_model)
                bm25 = BM25Index()
                indexing = IndexingService(
                    repo, store, bm25, models, cache,
                    ChunkerRegistry(
                        FIXED_CHARS if strategy is Strategy.FIXED else settings.chunk_max_chars,
                        settings.chunk_overlap,
                        settings.chunk_min_chars,
                    ),
                    IndexLimits(max_files_per_codebase=10**6, max_bytes_per_codebase=10**9),
                    strategy=strategy,
                )  # fmt: skip
                started = time.perf_counter()
                for codebase in SAMPLES:
                    indexing.index(codebase, sample_files(codebase), CodebaseKind.SAMPLE)
                index_s = time.perf_counter() - started
                retriever = Retriever(store, bm25, models, cache, repo, RetrievalSettings())
                for mode in SearchMode:
                    # The ranking does not depend on K: search once, score each K on a prefix.
                    hits, latencies = [], []
                    for example in examples:
                        tracer = Tracer("evaluate")
                        result = retriever.search(
                            example.question, example.codebases, max(KS), mode, tracer
                        )
                        latencies.append(tracer.finish().total_ms)
                        hits.append(result.hits)
                    for k in KS:
                        context = [sum(len(x.chunk.code) for x in h[:k]) for h in hits]
                        scored = [
                            retrieval_row(e, h[:k], k) for e, h in zip(examples, hits, strict=True)
                        ]
                        summary = summarize(scored, RETRIEVAL_METRICS, "metrics")
                        overall = summary["overall"]
                        rows.append(
                            {
                                "embedder": embed_model,
                                "strategy": strategy.value,
                                "mode": mode.value,
                                "k": k,
                                "chunks": store.count(),
                                "index_s": round(index_s, 1),
                                **{m: overall[m] for m in ("precision", "recall", "mrr", "ndcg")},
                                "latency_p50_ms": percentile(latencies, 50),
                                "context_chars": round(sum(context) / len(context)),
                                "by_category": {
                                    c: {m: v[m] for m in ("recall", "mrr")}
                                    for c, v in summary["by_category"].items()
                                    if v["n"]
                                },
                            }
                        )
                        print(_line(rows[-1]), flush=True)
    return {"kind": "grid", "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": rows,
            "summary": _best(rows), "n_examples": len(examples)}  # fmt: skip


def _line(r: dict) -> str:
    return (
        f"| {r['embedder'].split('/')[-1]} | {r['strategy']} | {r['mode']} | {r['k']} | "
        f"{r['precision']:.3f} | {r['recall']:.3f} | {r['mrr']:.3f} | {r['ndcg']:.3f} | "
        f"{r['chunks']} | {r['context_chars']:,} |"
    )


def _best(rows: list[dict]) -> dict:
    at5 = [r for r in rows if r["k"] == 5]
    best = max(at5, key=lambda r: (r["mrr"], r["recall"]))
    return {"best_at_5": {k: best[k] for k in ("embedder", "strategy", "mode", "recall", "mrr")}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--embedders", nargs="+", default=list(EMBEDDERS))
    args = parser.parse_args()
    print("| embedder | chunking | mode | K | P@K | R@K | MRR | nDCG | chunks | context chars |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    grid = run(args.embedders)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "grid.json").write_text(json.dumps(grid, indent=1))
    print("best at K=5:", grid["summary"]["best_at_5"])


if __name__ == "__main__":
    main()
