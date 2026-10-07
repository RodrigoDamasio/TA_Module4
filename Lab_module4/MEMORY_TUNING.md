# Memory tuning for the Railway free plan

How the backend's memory (RAM) was reduced so it can run on Railway's free plan, and what that
costs. Measured on 2026-10-07.

**Status:** measured locally, **not deployed yet**. Every change is an environment variable:
no code was changed, and the defaults in [backend/app/config.py](backend/app/config.py) stay as
they are for local work and tests.

## 1. The problem

Railway's free plan gives each service **0.5 GB (512 MB) of RAM**. A service that goes over the
limit is killed and restarted, and the request it was handling fails.

The backend runs two local ONNX models (the `bge-small` embedder and the MS MARCO cross-encoder
reranker), ChromaDB and an in-memory BM25 index. With the default settings it does not fit:

| Moment | Memory (default settings) |
|---|---|
| Idle, after startup | 440 MB |
| After the first search with rerank | 667 MB |
| After a retrieval evaluation with rerank | 964 MB |
| After indexing a 50-file codebase | **1,145 MB** |

Most of the growth is ONNX Runtime memory. It grows to fit the largest batch it has processed and
does not give memory back. The reranker scores 20 candidates in one batch, so a single rerank
request adds over 200 MB.

## 2. The changes

| # | Variable | Default | Railway value | What it does |
|---|---|---|---|---|
| 1 | `RERANK_MODEL` | `Xenova/ms-marco-MiniLM-L-6-v2` | `""` (empty) | Does not load the cross-encoder. `hybrid_rerank` requests fall back to `hybrid` |
| 2 | `EMBED_BATCH_SIZE` | `4` | `1` | Embeds one chunk at a time, so ONNX never allocates buffers for 4 long chunks at once |
| 3 | `ONNX_THREADS` | `2` | `1` | One inference thread: fewer per-thread buffers. Railway's free plan has 1 vCPU anyway |
| 4 | `MALLOC_ARENA_MAX` | glibc default (8 × cores) | `2` | Limits how many memory pools glibc's `malloc` creates for threads. Fewer pools means less memory held but unused |
| 5 | `MAX_USER_CODEBASES` | `10` | `3` (suggested) | Caps how many uploaded codebases can exist at once, so the index cannot grow without limit. Not measured, see §5 |

Change 1 is the fallback already planned in [BACKEND_PLAN §13](BACKEND_PLAN.md#13-deployment-railway).
Changes 2–4 were found while measuring for this deploy.

## 3. Results

All runs use `LLM_MODE=fake` (0 Gemini calls) and report the peak memory of the server process
(`VmHWM`).

**Each change on its own, then together** (index 50 files, 241 chunks, then a retrieval evaluation):

| Settings | Idle | Peak |
|---|---|---|
| Default (rerank on) | 440 MB | 1,145 MB |
| Rerank off (change 1) | 350 MB | 544 MB |
| Rerank off + `MALLOC_ARENA_MAX=2` | 343 MB | 521 MB |
| Rerank off + `ONNX_THREADS=1` | 347 MB | 514 MB |
| **Rerank off + batch 1 + 1 thread + `MALLOC_ARENA_MAX=2`** | 342 MB | **376 MB** |

No single change is enough. Only the combination stays clearly below 512 MB.

**Worst single codebase the API accepts** (all changes 1–4): 155 files, ~890 KB, ~1,200 chunks,
sent as 4 index requests (the limit is 1 MB per codebase).

| Step | Memory |
|---|---|
| Idle | 364 MB |
| After request 1 (421 chunks) | 416 MB |
| After requests 2–4 | 423 → 426 → 427 MB |
| After a search over all codebases and a retrieval evaluation | **430 MB** |

That leaves about **80 MB of headroom**. Most of the growth happens on the first index request
(ONNX warms up its buffers once); after that, each ~400 chunks added only 1–7 MB.

**Speed** (same 421-chunk request, rerank off):

| Settings | Index time | Uncached search |
|---|---|---|
| Default (batch 4, 2 threads) | 87 s | 29 ms |
| Lean (batch 1, 1 thread, `MALLOC_ARENA_MAX=2`) | 99 s (+14 %) | 44 ms |

Searches whose query embedding is cached take ~4 ms with both settings.

## 4. Pros and cons

### Turning the reranker off (change 1)

| Pros | Cons |
|---|---|
| Saves ~90 MB at idle and over 200 MB at peak. It's the biggest single change | The live demo loses one of the lab's extensions (reranking). It still exists in the code, the tests and [EVALUATION.md](EVALUATION.md) |
| Answer quality does not change: `hybrid` is already the default mode, and the evaluation showed reranking made ranking worse on this corpus (MRR 0.694 vs 0.803 for `hybrid`, [EVALUATION §2](EVALUATION.md#2-search-modes-extensions-hybrid-search-reranking)) | It found one more target (R@5 0.838 vs 0.815). That small recall gain is lost |
| One less model to download on first start (~80 MB less on the volume, faster cold start) | A user who picks `hybrid_rerank` gets `hybrid` instead. The API says so (`mode: "hybrid"`, `rerank_skipped: "disabled"` in the debug view, empty `reranker` in `meta`), but the frontend must show it clearly |
| Requests that asked for rerank are faster (no ~0.5–1.6 s cross-encoder step) | |

### Batch size 1 and one ONNX thread (changes 2 and 3)

| Pros | Cons |
|---|---|
| Together with change 4, they cut the indexing peak from 544 MB to 376 MB | Indexing is ~14 % slower on this machine (8 cores). On Railway's single vCPU the difference should be smaller, because a second thread has no spare core to run on there |
| Memory no longer depends on how many long chunks happen to arrive together, so the peak is more predictable | Uncached searches take ~15 ms longer (44 ms vs 29 ms). Not noticeable next to a 2–8 s Gemini answer |
| Retrieval results are the same: batch size and thread count don't change the vectors | |

### `MALLOC_ARENA_MAX=2` (change 4)

| Pros | Cons |
|---|---|
| A standard setting for multi-threaded Python servers in small containers. It stops glibc keeping many partly empty memory pools | Threads compete more for the same memory pools. With one Gemini call at a time and a single job worker, that is not a bottleneck here |
| An environment variable only: nothing in the code changes | It only affects Linux with glibc (which is what Railway runs). It does nothing on macOS or Alpine images |

### `MAX_USER_CODEBASES=3` (change 5, suggested)

| Pros | Cons |
|---|---|
| Puts a ceiling on index growth: only one 1 MB codebase was measured, and every extra one adds vectors, BM25 entries and Chroma memory | At most 3 uploaded codebases at once. A 4th upload is refused until one expires (24 h TTL) or is deleted |
| Easy to raise later if Railway's memory chart shows room | The value is an estimate, not a measurement (see §5) |

### Overall

| Pros | Cons |
|---|---|
| Fits the free plan: peak ~430 MB in the worst measured case | ~80 MB of headroom only. An unusual input could still go over the limit |
| No code changes, easy to undo: on a bigger plan, remove the variables | The live demo is not exactly what was evaluated: `hybrid_rerank` is unavailable |
| Retrieval quality of the default mode (`hybrid`) is unchanged | Slower indexing, especially for large uploads |

## 5. Risks and checks after the deploy

- **Local is not Railway.** These are the process's memory measured on this machine. Railway counts
  the whole container, which can be a little higher. After the deploy, check Railway's memory chart
  while indexing (check V9 in [BACKEND_PLAN §13](BACKEND_PLAN.md#13-deployment-railway)).
- **Several uploaded codebases were not measured.** From the growth seen in §3 (a few MB per 400
  chunks after the first request), 3 full codebases are estimated at ~450–470 MB. That's why change 5
  suggests 3 rather than the default 10. Test it after the deploy before raising the limit.
- **If the service still runs out of memory:** lower `MAX_USER_CODEBASES` and the per-codebase
  limits (`MAX_BYTES_PER_CODEBASE`), or move to Railway Hobby (8 GB). Hobby also allows turning
  the reranker back on.

## 6. Reproduce

From `backend/`, with the models already in `models/`:

```bash
env RERANK_MODEL="" ONNX_THREADS=1 EMBED_BATCH_SIZE=1 MALLOC_ARENA_MAX=2 \
    LLM_MODE=fake DATABASE_PATH=/tmp/rag.db CHROMA_PATH=/tmp/chroma \
    ../../../.venv/bin/python -m uvicorn app.main:app --port 8000
# in another terminal: index files with POST /index/files?wait=true, then
grep VmHWM /proc/$(pgrep -f "uvicorn app.main:app --port 8000")/status
```
