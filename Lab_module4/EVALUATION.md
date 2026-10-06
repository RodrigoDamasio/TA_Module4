# Evaluation — Codebase RAG

Results for the backend in [backend/](backend/), measured on 2026-10-05. Raw data:
[backend/eval/results/grid.json](backend/eval/results/grid.json) (retrieval grid) and
[backend/eval/results/full.json](backend/eval/results/full.json) (answers + judge).

## Setup

| Item | Value |
|---|---|
| Corpus | Two sample codebases written for the lab: `shopflow` (23 files: FastAPI backend, TypeScript web client, docs) and `ledger` (9 files: Hono API, Python worker). 32 files, ~37 KB |
| Dataset | 20 questions ([dataset.json](backend/eval/dataset.json)): 5 symbol, 4 conceptual, 4 location, 3 multi-file, 2 cross-codebase, 2 unanswerable. Ground truth is `path + symbol`, resolved to line ranges by parsing the files |
| Relevance | A retrieved chunk is relevant when its lines overlap a ground-truth range. Unanswerable questions are left out of retrieval averages (18 scored) |
| Embedders | `BAAI/bge-small-en-v1.5` (384 dims, 512 tokens) and `all-MiniLM-L6-v2` (384 dims, 256 tokens), local ONNX via fastembed |
| Reranker | `Xenova/ms-marco-MiniLM-L-6-v2` cross-encoder, local ONNX |
| LLM | `gemini-3.5-flash-lite` (answers and judge), prompt version 2 |
| Cost | Retrieval grid: **0 API calls**. Full evaluation: **49** real calls the first time, 4 more after a parser fix, **0** on every re-run (cached). Plus 2 calls for an initial smoke test: 55 in total |

## 1. Chunking strategies

K = 5, `bge-small`. "Context" is the average number of characters the top 5 chunks would send to the LLM.

| Chunking | Chunks | Mode | P@5 | R@5 | MRR | nDCG | Context |
|---|---|---|---|---|---|---|---|
| Fixed-size, 500 chars (course Strategy 1) | 97 | vector | 0.444 | 0.801 | 0.678 | 0.700 | 2,062 |
| Fixed-size, 500 chars | 97 | hybrid | 0.444 | 0.801 | 0.775 | 0.743 | 2,105 |
| Code-aware, no header | 50 | vector | 0.256 | 0.718 | 0.653 | 0.616 | 3,518 |
| Code-aware, no header | 50 | hybrid | 0.289 | 0.829 | 0.724 | 0.690 | 3,697 |
| **Code-aware + header** (default) | 53 | vector | 0.300 | 0.815 | 0.775 | 0.726 | 3,629 |
| **Code-aware + header** (default) | 53 | **hybrid** | 0.300 | **0.815** | **0.803** | 0.739 | 3,746 |

**What changed during the lab:** the first code-aware version made one chunk per function, class and import block. Those chunks had a median of **216 characters** (49 of 110 under 200), far below the course's 200–1000-token guideline (§2.3). A 2-line `class AuthError` or a list of imports is full of identifiers, so it matched many questions and pushed the real answers down. That version scored **R@5 0.732, MRR 0.733** (vector) and lost to the fixed-size baseline.

Packing neighbouring small units of the same scope up to ~700 characters (≈ 200 tokens) fixed it:

| Code-aware, bge, K = 5 | Chunks | Median size | vector R@5 / MRR | hybrid R@5 / MRR |
|---|---|---|---|---|
| One chunk per unit | 110 | 216 chars | 0.732 / 0.733 | 0.718 / 0.643 |
| Packed to ≥ 700 chars | 53 | 640 chars | 0.815 / 0.775 | 0.815 / 0.803 |

**Context headers matter:** without the `# file: … · class … · def …` line, MRR drops from 0.775 to 0.653 (vector). A function body alone often doesn't say which file or feature it belongs to.

**Why fixed-size still has the best precision:** its 500-character windows are smaller, and line-overlap relevance gives credit to any window that touches a target. Code-aware chunks are bigger (and cost ~1.7× more context per question). On ranking quality (MRR), which decides what the LLM reads first, code-aware + header is ahead.

## 2. Search modes (extensions: hybrid search, reranking)

Code-aware + header, bge, K = 5:

| Mode | R@5 | MRR | Query latency p50 |
|---|---|---|---|
| vector | 0.815 | 0.775 | ~4 ms (query embedding cached) |
| bm25 | 0.736 | 0.713 | < 1 ms |
| **hybrid** (weighted RRF 0.7 / 0.3, the course's weights) | 0.815 | **0.803** | ~4 ms |
| hybrid_rerank (cross-encoder over the top 20) | **0.838** | 0.694 | ~1.6 s on a busy CPU (~0.5 s idle) |

- **Hybrid** gives the best MRR. BM25 adds exact identifier matches (`processOrder`, `apply_discount`) that vectors rank lower.
- **Reranking** finds one more target (recall +0.02) but orders worse (MRR −0.11). The cross-encoder was trained on web search passages (MS MARCO), not code; it helped on `c4`, `l2`, `l4`, `x1` and hurt on `s5`, `c3`. A code-trained reranker would likely do better, but those models are much larger (≥ 1 GB).
- **Decision:** `hybrid` is the default mode; `hybrid_rerank` stays selectable.
- **RRF weights:** in the first grid (unpacked chunks), plain unweighted RRF scored below vectors alone (MRR 0.625 vs 0.733): weak keyword hits on natural-language questions pushed good vector hits down. The course's 0.7 / 0.3 weights were adopted then. Unweighted RRF was not re-measured on packed chunks.

## 3. Embedding models

| Code-aware + header, K = 5 | vector R@5 / MRR | hybrid R@5 / MRR | hybrid_rerank R@5 / MRR |
|---|---|---|---|
| **bge-small-en-v1.5** | 0.815 / 0.775 | **0.815 / 0.803** | 0.838 / 0.694 |
| all-MiniLM-L6-v2 | 0.727 / 0.676 | 0.796 / 0.745 | 0.866 / 0.706 |

bge-small is better on its own (+0.10 MRR with vectors only) and its 512-token window fits every packed chunk (checked with the real tokenizer in `pytest -m models`). MiniLM is ~2.5× faster to embed but truncates at 256 tokens. The optional Gemini-embedding comparison was not run, to save quota for the answer evaluation.

## 4. How many chunks to send (K)

Default configuration (code-aware + header, bge, hybrid):

| K | P@K | R@K | MRR | Context chars |
|---|---|---|---|---|
| 3 | 0.407 | 0.690 | 0.778 | 2,251 |
| **5** | 0.300 | 0.815 | 0.803 | 3,746 |
| 10 | 0.189 | 0.944 | 0.803 | 7,161 |

K = 5 is the default: K = 10 finds more targets (0.94) at about twice the context. The API accepts `k` up to 10.

## 5. Answers (LLM-as-judge and deterministic checks)

Full run with the default configuration (K = 5, hybrid). One judge call per question returns three 1–5 scores (course §5.3 rubrics).

| Metric | Result | Target ([BACKEND_PLAN §9.4](BACKEND_PLAN.md#94-full-evaluation-answers--judge)) |
|---|---|---|
| Recall@5 / MRR | 0.815 / 0.803 | ≥ 0.80 / ≥ 0.70 ✅ |
| Faithfulness / relevance / correctness (avg, 18 answered) | **5.00 / 4.89 / 4.72** | ≥ 4.0 / ≥ 4.0 / ≥ 3.5 ✅ |
| Citations valid (deterministic) | 20 / 20 | 100 % ✅ |
| Unanswerable → `found: false` | 2 / 2 | 2 / 2 ✅ |
| `found` matches the expectation | 19 / 20 | — (x1, see below) |
| Planted prompt injection followed | 0 / 20 | 0 ✅ |
| Judge sanity check (planted bad answers scored ≤ 2) | **4 / 4** | 4 / 4 ✅ |
| Required terms mentioned | 14 / 20 | — (see below) |
| `hybrid_rerank` MRR not lower than `vector` | 0.694 < 0.775 | ❌ → default changed to `hybrid` (§2) |
| Real calls, first full run | 49 | ≤ 50 ✅ |
| Latency per question (answer + judge, real calls) | p50 4.2 s, p95 8.3 s | — |

**By category** (correctness / R@5): symbol 5.0 / 1.00 · conceptual 5.0 / 0.92 · location 4.75 / 0.88 · multi-file 4.33 / 0.50 · cross-codebase 4.0 / 0.50.

**Judge sanity check:** the judge gave correctness 1 to all four planted bad answers (wrong function, invented config file, unsupported claim added to a correct answer, off-topic). Module 3's verifier gave 10/10 to everything; this judge does discriminate. It still gave faithfulness 5 to every real answer, which matches what we read (the answers stick to the excerpts), but it is the same model grading itself, so treat the averages as an upper bound.

### What went wrong, and why

| Question | Problem | Cause |
|---|---|---|
| `x1` "Which web framework does each project use?" | Answered only for Ledger and said the excerpts don't show Shopflow's framework (`found: false`, correctness 3) | **Retrieval miss:** `backend/app/main.py` (the `FastAPI()` app) was not in the top 5. Cross-codebase questions are the weakest category (R@5 0.50). The model behaved correctly: it did not guess |
| `m3` "How does the web app send the login token?" | Did not mention the `Authorization` header | `apiFetch` (which sets the header) ranked below `AuthProvider`; the answer stayed with what it was given |
| `l2` "How long do tokens last?" | Named `JWT_TTL_MINUTES` but not its default of 60 | The `get_settings` chunk was retrieved, but the model skipped the default |
| `s4`, `c4`, `m1` | Correct answers that paraphrased the required term ("balance in integer cents" instead of `balanceCents`) | The `must_mention` check is strict on exact words; the judge scored these 5/5/5 and 5/5/4 |

### Fixed during the evaluation

- **Grouped citations:** Gemini writes `[1, 2, 3]`; the first parser only understood `[1]`. Five correct answers were marked ungrounded and each spent a repair call. Fixed, and covered by a unit test.
- **Missing inline markers:** in the very first call the model filled the `citations` list but left the `[n]` markers out of the text. The schema fields now describe where markers go (prompt v2), and a valid list without inline markers is accepted instead of spending a repair call.

## 6. Limitations

- **Small dataset:** 18 scored questions. One question moves recall or MRR by ~0.05, so differences under ~0.05 are noise.
- **Same author:** the questions and the sample code were written together, which usually makes metrics optimistic. Paraphrased, conceptual, cross-codebase and unanswerable questions are included to push back on that, and results are reported per category.
- **Line-overlap relevance** rewards bigger chunks (any chunk that touches a target counts). The "context chars" column shows the price of that.
- **Self-grading:** answers and grades come from the same model. The sanity check shows the judge rejects clearly bad answers; it does not prove it catches subtle ones.

## 7. Reproduce

```bash
cd backend
python -m eval.grid                            # 0 calls, a few minutes the first time
python -m eval.run --max-calls 60 --publish    # real Gemini the first time, then 0 (cached)
pytest -m models                               # real models + retrieval regression vs eval/baseline.json
```
