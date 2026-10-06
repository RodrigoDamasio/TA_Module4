# Codebase RAG — backend

FastAPI service that indexes code, answers questions from it with citations, and measures
retrieval and answer quality. Design: [../BACKEND_PLAN.md](../BACKEND_PLAN.md). Results:
[../EVALUATION.md](../EVALUATION.md).

- **Chunking:** Python by `ast`, TypeScript/JavaScript by tree-sitter, Markdown by heading,
  fixed-size windows for everything else. Small neighbouring units are packed to ~700
  characters, and every chunk carries a context header (file, class, signature).
- **Search:** local ONNX embeddings (`BAAI/bge-small-en-v1.5`, no PyTorch) in ChromaDB,
  plus an incremental BM25 index, merged with weighted Reciprocal Rank Fusion. An optional
  local cross-encoder reranker. Modes: `vector`, `bm25`, `hybrid` (default),
  `hybrid_rerank`.
- **Answers:** one Gemini call per question (`gemini-3.5-flash-lite`), structured output,
  citations checked in code, one repair at most. Identical prompts are served from a cache.
- **Evaluation:** Precision@K, Recall@K, MRR, nDCG (0 calls), and an LLM judge
  (faithfulness, relevance, correctness in one call) with a sanity check on planted bad
  answers.
- **Observability:** per-request traces with every stage's timing and scores, JSON logs
  without questions or code, `GET /stats`, and `?debug=true` for the full pipeline.

## Run locally

From this folder, with the shared virtual environment at the repository root:

```bash
../../../.venv/bin/pip install -r requirements-dev.txt

# No key, no model download: fake LLM + hashing embedder (UI work, E2E)
LLM_MODE=fake EMBED_MODE=fake ../../../.venv/bin/uvicorn app.main:app --port 8000

# Real: local ONNX models (downloaded once to ./models, ~150 MB) + Gemini
set -a; . ../../../.env; set +a
../../../.venv/bin/uvicorn app.main:app --port 8000
```

The two sample codebases (`shopflow`, `ledger`) are indexed at startup from
`samples/snapshot/` in a few seconds. API docs: http://localhost:8000/docs.

```bash
curl -s localhost:8000/query -H 'content-type: application/json' \
  -d '{"question": "How does authentication work?", "codebases": ["shopflow"]}'
curl -s 'localhost:8000/query?debug=true' -H 'content-type: application/json' \
  -d '{"question": "Where is the database connection configured?", "codebases": ["shopflow"]}'
curl -s localhost:8000/index/files?wait=true -H 'content-type: application/json' \
  -d '{"codebase": "my-api", "files": [{"path": "app.py", "content": "def hi():\n    return 1\n"}]}'
```

## Tests

| Suite | Command | Real Gemini calls |
|---|---|---|
| Unit, component, API, integration, architecture | `../../../.venv/bin/python -m pytest` | 0 |
| Coverage | `... -m pytest --cov=app` | 0 |
| Real ONNX models + retrieval regression | `... -m pytest -m models` | 0 |
| Lint | `... -m ruff check . && ... -m ruff format --check .` | 0 |

`UPDATE_BASELINE=1 ... -m pytest -m models` rewrites `eval/baseline.json` after an intended
retrieval change.

## Evaluation

| Script | What | Real calls |
|---|---|---|
| `python -m eval.grid` | Chunking × search mode × K × embedder, writes `eval/results/grid.json` | 0 |
| `python -m eval.build_snapshot` | Sample chunks + vectors for fast startup | 0 |
| `python -m eval.run --max-calls 60 --publish` | Answers + judge + checks + judge sanity; writes `eval/results/full.json` and the answer cache seed | ~45 first run, 0 after (cached in `eval/eval.db`) |

## Configuration

All settings are environment variables (`app/config.py`). The main ones:

| Variable | Default | Purpose |
|---|---|---|
| `GOOGLE_API_KEY` | — | Gemini key (never logged) |
| `LLM_MODE` / `EMBED_MODE` | `gemini` / `onnx` | `fake` for tests and UI work |
| `DATABASE_PATH` / `CHROMA_PATH` / `MODELS_PATH` | `rag.db` / `chroma` / `models` | Storage (Railway: under `/data`) |
| `EMBED_MODEL` / `RERANK_MODEL` | bge-small / ms-marco-MiniLM | `RERANK_MODEL=""` disables reranking (saves ~225 MB) |
| `DEFAULT_MODE` | `hybrid` | Search mode when a request does not choose one |
| `CHUNK_MAX_CHARS` / `CHUNK_MIN_CHARS` | `1400` / `700` | Chunk size bounds |
| `FULL_EVAL_MAX_CALLS` | `0` | Real calls a full evaluation may spend (0 = cached answers only) |
| `PIPELINE_DEBUG_ENABLED` | `true` | Allows `?debug=true` |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | CORS (comma-separated) |
