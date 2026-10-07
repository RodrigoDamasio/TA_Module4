# Backend Deployment — Railway

The exact steps used to deploy the Codebase RAG API, in the order they were run on 2026-10-07.

**Result:** https://backend-production-cf2a.up.railway.app ([API docs](https://backend-production-cf2a.up.railway.app/docs))

| Item | Value |
|---|---|
| Railway project | `taller-codebase-rag` |
| Service / environment | `backend` / `production` |
| Volume | `backend-volume` mounted at `/data`: `rag.db` (index, caches, jobs, traces), `chroma/`, `models/` |
| Builder | Railpack, Python 3.12, pip |
| Plan limits (shown by `railway metrics`) | 2 vCPU, **1,024 MB RAM**, 500 MB volume |
| Models | `BAAI/bge-small-en-v1.5` embedder only. **Reranker off** to save memory, see [MEMORY_TUNING.md](../MEMORY_TUNING.md) |
| LLM | `gemini-3.5-flash-lite` (Google AI Studio free tier) |
| Replicas | **1**: the job queue and BM25 index are in-process and the store is SQLite. Do not scale horizontally |

## Prerequisites

- Railway CLI logged in.
- `GOOGLE_API_KEY` in the course's `.env` (`Taller_Academy/.env`, git-ignored).
- Gates green: `pytest -q` (118 tests, 0 LLM calls), `ruff check .`, `ruff format --check .`.
- Work committed and pushed (rollback point `89efa0a`).
- **Free plan: at most 2 projects.** Both were in use (Modules 2 and 3). The owner chose to delete the Module 2 project
  (`taller-code-analyzer`): `railway delete --project <id> --yes`. Railway takes its backend offline at once and deletes
  the project for good after 48 hours. The Module 2 code remains on GitHub; its frontend no longer works.

## Files that configure the deploy

| File | Purpose |
|---|---|
| `requirements.txt` + `.python-version` | Python 3.12 pip project. No PyTorch: ONNX models through `fastembed` |
| `railpack.json` | Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'`. The proxy headers give the real client IP to the rate limiter |
| `railway.json` | Health check `GET /health`. Railway deprecates this format after 2026-12-01; migrate with `railway config migrate` |
| `.railwayignore` | Keeps `tests/`, local databases, `chroma/` and `models/` (239 MB) out of the upload. `samples/` **is** deployed: the samples load from `samples/snapshot/` (no embedding at startup) and the LLM cache seed lives there too |

## Steps

```bash
cd TA_Module4/Lab_module4/backend

# 1. Project, service (with the DB path), volume, public domain
railway init --name taller-codebase-rag --workspace <workspace-id>
railway add --service backend --variables "DATABASE_PATH=/data/rag.db"
railway service link backend
railway volume add --mount-path /data
railway domain --json            # → https://backend-production-cf2a.up.railway.app

# 2. Non-secret settings: storage on the volume, model, no real calls for /evaluate full,
#    and the memory settings from MEMORY_TUNING.md
railway variables --set "BASE_URL=https://backend-production-cf2a.up.railway.app" \
  --set "GEMINI_MODEL=gemini-3.5-flash-lite" \
  --set "CHROMA_PATH=/data/chroma" --set "MODELS_PATH=/data/models" --set "FULL_EVAL_MAX_CALLS=0" \
  --set "RERANK_MODEL=" --set "ONNX_THREADS=1" --set "EMBED_BATCH_SIZE=1" --set "MALLOC_ARENA_MAX=2" \
  --set "MAX_USER_CODEBASES=3" --skip-deploys

# 3. API key (run by the owner): piped from .env, never on the command line,
#    in history, or in output. Then compare fingerprints, not values.
grep '^GOOGLE_API_KEY=' ../../../.env | cut -d= -f2- | tr -d '\n' \
  | railway variable set GOOGLE_API_KEY --stdin --skip-deploys > /dev/null
a=$(railway variables --kv | grep '^GOOGLE_API_KEY=' | cut -d= -f2- | tr -d '\n' | sha256sum)
b=$(grep '^GOOGLE_API_KEY=' ../../../.env | cut -d= -f2- | tr -d '\n' | sha256sum)
[ "$a" = "$b" ] && echo "key matches"
railway variables --kv | cut -d= -f1          # names only

# 4. Deploy (~4 minutes: build, then the embedder downloads into /data/models on first start)
railway up --ci
```

**After the frontend is on Vercel.** This sets CORS and redeploys automatically:

```bash
railway variables --set "FRONTEND_ORIGIN=http://localhost:3000,https://<vercel-domain>"
```

## Final environment variables

| Variable | Value | Why |
|---|---|---|
| `GOOGLE_API_KEY` | *(secret, set via stdin)* | |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Free-tier model with the highest daily limit |
| `DATABASE_PATH` | `/data/rag.db` | On the volume |
| `CHROMA_PATH` / `MODELS_PATH` | `/data/chroma` / `/data/models` | On the volume. The model downloads once and survives redeploys |
| `BASE_URL` | `https://backend-production-cf2a.up.railway.app` | Absolute problem `type` URLs |
| `FULL_EVAL_MAX_CALLS` | `0` | `POST /evaluate {mode: full}` only replays the seeded cache |
| `RERANK_MODEL` | *(empty)* | Reranker off. `hybrid_rerank` falls back to `hybrid` |
| `ONNX_THREADS` / `EMBED_BATCH_SIZE` | `1` / `1` | Lower, steadier memory peak |
| `MALLOC_ARENA_MAX` | `2` | Fewer glibc memory pools held by threads |
| `MAX_USER_CODEBASES` | `3` | Caps index growth |
| `FRONTEND_ORIGIN` | *(not set yet: default `http://localhost:3000`)* | Set after the Vercel deploy |

## Post-deploy verification (results)

| # | Check | Result | LLM calls |
|---|---|---|---|
| V1 | `/health`, `/codebases` | ✅ `{"status":"ok","models":"ready","samples":"snapshot"}`. `shopflow` (23 files, 43 chunks) and `ledger` (9 files, 10 chunks), both read-only | 0 |
| V2 | `/search` "processOrder" on `shopflow` | ✅ `web/src/orders/processOrder.ts` · `processOrder` at rank 1. `meta.mode = hybrid`, `meta.reranker = ""` | 0 |
| V3 | `POST /evaluate {mode: retrieval}` | ✅ P@5 0.300, R@5 0.8148, MRR 0.8028, nDCG 0.7389: **identical** to the local baseline ([eval/baseline.json](eval/baseline.json)) | 0 |
| V4 | `POST /evaluate {mode: full}` | ✅ Job `completed`, **`real_calls: 0`, `cached_calls: 42`**. Faithfulness / relevance / correctness 5.00 / 4.89 / 4.72, citations 20/20, judge sanity 4/4: same as [EVALUATION.md](../EVALUATION.md) | 0 |
| V5 | `/query` with a dataset question, then a new one | ✅ "What does the processOrder function do?" served from the cache (generation 0.6 ms). New question "Which HTTP status does the orders API return when stock is insufficient?" → "409" citing `orders/routes.py` and `processOrder.ts`; `/stats` shows `calls_today: 1` | 1 |
| V6 | Index a user codebase, search it, delete it | ✅ 3 files from Module 3's `test_files/` (`flask_notes`, `django_notes`) indexed in ~1 s (3 chunks). Search "create a new note" → `flask_notes/app.py` first. `DELETE` → 204, then `GET` → 404 | 0 |
| V7 | Error responses | ✅ All `application/problem+json`: missing field → `422 validation-error`; `secret.exe` → `422 unsupported-file-type`; 520 KB file → `413 input-too-large`; index into or delete `shopflow` → `409 codebase-read-only`. `/problems/validation-error` → 200 | 0 |
| V8 | CORS from `http://localhost:3000` | ✅ Preflight allows `GET, POST, DELETE` and `Content-Type`. A `404` problem carries `access-control-allow-origin` and exposes `Retry-After, Location`. Another origin gets no CORS header. To repeat with the Vercel origin after the frontend deploy | 0 |
| V9 | Memory, volume, logs | ✅ Memory **max 393 MB** of 1,024 MB (`railway metrics`, after V1–V8). Volume 115 MB of 500 MB. 379 log lines: 0 matches for `GOOGLE_API_KEY`, `AIza`, question text or indexed code (`processOrder function`, `insufficient`, `list_notes`, `def add_note`); no `Traceback`, `Killed` or `OOM`. The index log has ids and counts only (`codebase=notes-demo files=3`) | 0 |

**Total: 1 real Gemini call** for the whole deploy and its checks.

## Problems hit

- **Railway free plan project limit.** Solved by deleting the Module 2 project, as described in the prerequisites.
- **The memory limit was assumed to be 512 MB.** Third-party pricing pages describe the free plan as 0.5 GB per
  service, so the backend was tuned for that ([MEMORY_TUNING.md](../MEMORY_TUNING.md)). `railway metrics` shows
  **1,024 MB** for this service. The tuning still matters: the default settings peaked at 1,145 MB locally, above 1 GB too.
- **Setting the key from the assistant's session** is blocked by Claude Code's permission check, so the owner ran step 3
  in their own terminal, as planned.

## Quota notes

- The deployed app shares the key's free-tier quota with every caller of the public URL.
- What costs nothing: `/search`, `/evaluate` (retrieval, and full replayed from the seeded cache), indexing (local
  embeddings), and any question asked before (LLM response cache on the volume).
- What costs calls: a new `/query`, 1 call (2 if the answer needs a repair).
- Protections: per-IP rate limits (query 10/min and 50/day, index 5/min and 20/day, search 30/min), input size limits,
  one Gemini call at a time with pacing, a daily request counter (`LLM_DAILY_REQUEST_LIMIT=1000`), and a circuit
  breaker after the daily quota, which refuses new questions with `503`.
- Billing is **not** enabled on the Google project. The worst case is "limit reached" until midnight Pacific, never a charge.

## Redeploy / rollback

```bash
pytest -q && ruff check . && git commit ...   # gates + rollback point
railway up --detach --service backend --environment production
```

On 2026-10-07 (adding `GET /config`), plain `railway up --ci` failed with "Free plan resource provision limit
exceeded" while the deleted Module 2 project was still pending removal; naming the service and environment
deployed normally. Follow the deployment with `railway deployment list` and `/health`.

Rollback: in the Railway dashboard, open `backend` → Deployments → the previous deployment → Redeploy. The volume is
not affected. Jobs queued or running during a redeploy are marked failed at startup ("Interrupted by a server
restart"); files an interrupted index job already indexed stay indexed.

**Turning the reranker back on** needs more memory than the plan gives with the default settings (see
[MEMORY_TUNING.md](../MEMORY_TUNING.md)). Measure locally with the lean settings plus
`RERANK_MODEL=Xenova/ms-marco-MiniLM-L-6-v2` first.
