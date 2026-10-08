# Pipeline walkthrough

Two flows, step by step, with the code that runs each step:

1. [Indexing a codebase](#1-indexing-a-codebase): what happens when you upload code, until it is stored in ChromaDB.
2. [Retrieving code for a question](#2-retrieving-code-for-a-question): how the chunks for a question are found
   (the retrieval part of the query diagram in [PLAN.md](PLAN.md)).

The flows share one thing: chunks and questions are embedded by the **same model** (`BAAI/bge-small-en-v1.5`, local
ONNX), so they land in the same 384-dimension space and can be compared.

**Runs on** says what does the work in each step. Everything is driven from Python; the column names the component
that does the heavy lifting:

| Component | What it is |
|---|---|
| **Browser** | The Next.js frontend (TypeScript) |
| **Python** | The FastAPI backend's own code |
| **ONNX** | The embedding and reranking models, run by `onnxruntime` through the `fastembed` library (compiled engine, no PyTorch) |
| **ChromaDB** | The vector database, embedded in the API process (a library, not a separate server); data in `/data/chroma` |
| **SQLite** | `/data/rag.db`: file records, jobs, and the embedding and answer caches |
| **BM25** | The keyword index: pure Python, in memory, rebuilt from SQLite at every server start |

## 1. Indexing a codebase

Steps 1–2 run in the browser; everything after runs on the Railway backend.

| # | Step | Runs on | Main goal | Where it happens |
|---|---|---|---|---|
| 1 | **Pick files and review them** | **Browser** | Check the files with the server's own rules (from `GET /config`) before sending anything: skip `node_modules`/`dist`, lockfiles, `.env`, unsupported types, minified files, and stop if the codebase is over 200 files or 1 MB. Nothing the server would refuse is uploaded | [upload.ts:92](frontend/lib/upload.ts#L92) (`review`) |
| 2 | **Split into requests and send them** | **Browser** | Fit each request within 50 files / 500 KB, all into the same codebase, one after the other; follow each job until it ends | [upload.ts:153](frontend/lib/upload.ts#L153) (`batches`), [indexing.ts:80](frontend/lib/indexing.ts#L80) (`indexAll`), [indexing.ts:65](frontend/lib/indexing.ts#L65) (polls `GET /jobs/{id}`) |
| 3 | **`POST /index/files`: validate** | **Python** (+ SQLite, to read the existing codebases) | Refuse bad input at once with a clear `4xx` (name format, read-only sample, too many codebases, size limits, unsafe or duplicate paths) before any work is queued | [routes.py:79](backend/app/api/routes.py#L79) → [indexing.py:72-115](backend/app/application/indexing.py#L72-L115) (`validate`) |
| 4 | **Create a background job** | **Python** (in-process queue) + **SQLite** (`jobs` table) | Answer `202` at once, because embedding takes seconds to minutes. One worker thread runs the jobs, so uploads don't compete for the single CPU | [jobs.py:36-56](backend/app/application/jobs.py#L36-L56), [runner.py:32](backend/app/infrastructure/runner.py#L32) (`ThreadRunner`) |
| 5 | **Worker starts** | **Python** | Remove the file contents from the stored job (only the name and the count stay), and wait until the embedding model is loaded | [jobs.py:83-87](backend/app/application/jobs.py#L83-L87) |
| 6 | **Codebase record and per-file skip** | **Python** + **SQLite** | Create the codebase on first upload, with its 24 h expiry, and skip files the server won't index (same rules as step 1, reported as "Skipped by the server") | [indexing.py:117-141](backend/app/application/indexing.py#L117-L141) |
| 7 | **Skip unchanged files** | **Python** + **SQLite** (file records) | Compare the file's SHA-256 and chunker version with the stored ones: on a re-upload, unchanged files cost nothing (`files_unchanged`) | [indexing.py:143-149](backend/app/application/indexing.py#L143-L149) |
| 8 | **Code-aware chunking** | **Python**: the built-in `ast` parser for Python, **tree-sitter** for TypeScript/JavaScript, headings for Markdown | Cut the file along functions, classes and sections, so each chunk is one meaningful unit. Small neighbours are packed up to ~700 characters; units over 1,400 are split with overlap. Each chunk gets a header (`# file: … · class … · def …`) so it still says where it belongs. If parsing fails, fixed windows are used (the "fallback chunking" badge) | [registry.py:41-65](backend/app/chunking/registry.py#L41-L65) → `python_ast.py`, `typescript.py`, `markdown.py`, [splitting.py](backend/app/chunking/splitting.py) (`pack`, `make_header`) |
| 9 | **Embed the chunks (cached)** | **Python + SQLite** (cache lookup) → **ONNX** (only for new text) | Turn each chunk (header + code) into a 384-number vector of meaning. Identical text is never embedded twice: the cache key is the model + SHA-256 of the text | [indexing.py:155](backend/app/application/indexing.py#L155) → [embedding.py:29-41](backend/app/application/embedding.py#L29-L41) → [fastembed_models.py:26-29](backend/app/infrastructure/fastembed_models.py#L26-L29) |
| 10 | **Remove the file's old chunks** | **ChromaDB** + **BM25** | On a re-upload, delete the previous version's chunks first, so a changed file never leaves stale chunks behind | [indexing.py:198-199](backend/app/application/indexing.py#L198-L199) → [chroma_store.py:62-67](backend/app/infrastructure/chroma_store.py#L62-L67) |
| 11 | **Write to ChromaDB** | **ChromaDB** | Store each chunk's **id, vector, code and metadata** (codebase, path, lines, kind, header). Step 3 of the question flow searches this, and its codebase filter uses the `codebase` metadata | [indexing.py:201](backend/app/application/indexing.py#L201) → [chroma_store.py:46-57](backend/app/infrastructure/chroma_store.py#L46-L57) (`upsert`) |
| 12 | **Add to the keyword index** | **BM25** | Make the chunk findable by its exact words too: the keyword half of hybrid search | [indexing.py:202-203](backend/app/application/indexing.py#L202-L203) |
| 13 | **Save the file record** | **SQLite** | Remember the hash, chunker version, chunk count and fallback flag: what step 7 compares against next time, and what the Codebases page lists | [indexing.py:204-215](backend/app/application/indexing.py#L204-L215) |
| 14 | **Report progress and finish** | **Python** + **SQLite** (job row) | After each file, save files done, chunks and cache hits for the browser's progress line. At the end, update the codebase totals and mark the job `completed` with the result the upload panel shows | [indexing.py:173-181](backend/app/application/indexing.py#L173-L181) |
| — | **Expiry, 24 h later** | **Python** (sweeper thread) → **ChromaDB** + **SQLite** + **BM25** | Delete uploaded codebases when they expire, so storage and the upload slots (3 in production) free up. Samples never expire | [codebases.py:56](backend/app/application/codebases.py#L56) (`sweep_expired`) |

**Notes**
- ONNX runs in **one step only** (9), and only for text it hasn't seen before. That's why re-uploading an unchanged
  project, or the same code under another name, is fast and shows "embeddings from cache".
- Steps 11 and 12 fill what the question flow reads: ChromaDB serves the vector search, BM25 the keyword search.

## 2. Retrieving code for a question

The conductor of this flow is [retriever.py:58-150](backend/app/application/retrieval/retriever.py#L58-L150).

```
Retriever ──1──▶ Local ONNX models ──2──▶ Retriever ──3──▶ ChromaDB ──▶ Retriever
          ── BM25 top 20, then RRF merge ──▶ Retriever ──4──▶ Local ONNX models ──5──▶ Retriever (top k)
```

| # | Step | Runs on | Main goal | Where it happens |
|---|---|---|---|---|
| 1 | **bge-small embeds the question (cached)** | **Python + SQLite** (cache lookup) → **ONNX** (only on a cache miss) | Turn the question into a vector of meaning so it can be compared with the code, even when the words differ ("log in" vs `authenticate`). Asking again skips the model through the cache (key: SHA-256 of `"q:" + question`) | [retriever.py:70-73](backend/app/application/retrieval/retriever.py#L70-L73) → [embedding.py:43-52](backend/app/application/embedding.py#L43-L52) → [fastembed_models.py:31-32](backend/app/infrastructure/fastembed_models.py#L31-L32) |
| 2 | **query vector (384 dims)** | **ONNX** → Python list | Hand back the question's vector in the same 384-dimension space as the indexed chunks | value returned by `embed_query` |
| 3 | **nearest 20 chunks (codebase filter)** → **candidates + distances** | **ChromaDB** | Find the 20 chunks closest in meaning, searching only the selected codebases (`where: {codebase: {$in: [...]}}`). Similarity = 1 − distance | [retriever.py:80-87](backend/app/application/retrieval/retriever.py#L80-L87) → [chroma_store.py:76-83](backend/app/infrastructure/chroma_store.py#L76-L83) |
| — | **BM25 top 20, then RRF merge** | **BM25** + **Python** (no model, no database) | BM25 finds the chunks with the question's exact words, which catches names like `processOrder`. RRF combines both lists by rank (0.7 vectors / 0.3 keywords), so chunks found by both rise to the top | [retriever.py:89-98](backend/app/application/retrieval/retriever.py#L89-L98) → [bm25.py:103](backend/app/application/retrieval/bm25.py#L103); [retriever.py:106-118](backend/app/application/retrieval/retriever.py#L106-L118) → [fusion.py:20](backend/app/application/retrieval/fusion.py#L20) |
| 4 | **MiniLM cross-encoder scores 20 pairs** | **Python** (prepares header + code, cut to 800 characters) → **ONNX** (scores). **Off in production** | Rescore each candidate by reading the question and the chunk together (slower, but more precise than comparing two vectors), to put the best chunk first | [retriever.py:126-135](backend/app/application/retrieval/retriever.py#L126-L135) → [fastembed_models.py:43-46](backend/app/infrastructure/fastembed_models.py#L43-L46) |
| 5 | **scores, keep top k** | **Python** | Keep the K best chunks (5 by default): the numbered excerpts `[1]..[5]` that Gemini answers from and cites. A smaller prompt with less noise | [retriever.py:137-139](backend/app/application/retrieval/retriever.py#L137-L139) |

**Notes**
- **Step 4 never runs in production.** `RERANK_MODEL` is empty to fit the memory limit
  ([MEMORY_TUNING.md](MEMORY_TUNING.md)), so the reranker returns `(None, "disabled")`
  ([retriever.py:127-130](backend/app/application/retrieval/retriever.py#L127-L130)) and the search falls back to the
  RRF order, reported as `mode: hybrid`.
- **How well each step meets its goal** ([EVALUATION.md §2](EVALUATION.md#2-search-modes-extensions-hybrid-search-reranking)):
  BM25 + RRF raised MRR from 0.775 (vectors only) to 0.803. Reranking found one more relevant chunk (recall 0.838) but
  ranked the best one first less often (MRR 0.694): it was trained on web search, not code.
- **Every step is timed.** Each `with tracer.span(...)` block feeds the trace bar under each answer and the "How this
  answer was made" panel, so this exact flow can be watched per question in the frontend.
- **Known issue:** BM25's statistics span every indexed codebase, so an upload shifts the samples' keyword scores
  slightly ([frontend/DEPLOY.md](frontend/DEPLOY.md#known-issue-uploads-change-the-bm25-scores-of-other-codebases)).
