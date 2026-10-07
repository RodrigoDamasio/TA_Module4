# Frontend Deployment — Vercel

The steps run on 2026-10-07 to deploy the Codebase RAG UI. Same pattern as Modules 1–3.

**Result:** https://taller-codebase-rag.vercel.app

| Item | Value |
|---|---|
| Vercel scope / project | `rodrigodamasiojulio-9268` / `taller-codebase-rag` (Hobby) |
| Backend | https://backend-production-cf2a.up.railway.app ([../backend/DEPLOY.md](../backend/DEPLOY.md)) |
| Secrets | None. The Gemini key stays on Railway |

## Prerequisites

- Backend additions B1–B2 deployed first (`GET /config`, `reranker` in `/health`): the UI reads limits, file rules and
  available modes from the server.
- Gates green: `npm run typecheck`, `npm run lint`, `npm test` (95 tests), `npm run test:e2e` (8/8 locally, 0 AI calls).
- Work committed and pushed.

## Steps

```bash
cd TA_Module4/Lab_module4/frontend
# The Vercel CLI is installed under Node 18's global bin (nvm); the build runs on Vercel.
export PATH=/home/rodrigo/.nvm/versions/node/v18.18.2/bin:$PATH

# 1. Create and link the project (.vercel/ and .env.local are git-ignored)
vercel link --yes --project taller-codebase-rag

# 2. Backend URL: NEXT_PUBLIC_* is inlined at build time, so set it before deploying
printf 'https://backend-production-cf2a.up.railway.app' | vercel env add NEXT_PUBLIC_API_URL production

# 3. Deploy
vercel --prod --yes

# 4. Allow the Vercel origin on the backend (CORS; Railway redeploys the API) — from ../backend
railway variables --service backend --environment production \
  --set "FRONTEND_ORIGIN=http://localhost:3000,https://taller-codebase-rag.vercel.app"
```

## Verification

| Check | Result | Gemini calls |
|---|---|---|
| Pages public | ✅ `/`, `/codebases`, `/codebases/shopflow`, `/evaluation`: 200 | 0 |
| Bundle contains the Railway URL | ✅ in `/_next/static/immutable/chunks/…` | 0 |
| CORS from the Vercel origin (backend V8, repeated) | ✅ Preflight allows `GET, POST, DELETE`; a `404` problem carries `access-control-allow-origin: https://taller-codebase-rag.vercel.app` and exposes `Retry-After, Location` | 0 |
| E2E against production (`BASE_URL=… npm run test:e2e`) | ✅ 7/7 (the error-handling test uses mocked routes and runs locally only) | **1** |

**What the production E2E did:**
- **E2, E3:** suggested questions (`processOrder`, database connection): answered from the server's cache, citations jump
  to their sources, the pipeline view shows candidates, matched terms and the prompt.
- **E4:** search only across `shopflow` + `ledger`.
- **E1:** uploaded `test_files/auction_checklist` as **`e2e-auction-checklist`** (its own name, so a real upload with the
  same files is never touched), browsed `auction/costs.py`'s chunks, asked one new question about it (**the 1 real
  call**: the answer cited `auction/costs.py`), then deleted it.
- **E5:** stored report and grid; a retrieval run; a full replay with **0 real calls**.
- **E7, E8:** no horizontal scroll at 375 px on every page; axe finds no serious or critical violations.

`/stats` read 0 real calls before the run and 1 after.

## Problems hit

- **The full replay showed "Something went wrong" in production.** Questions skipped by the replay (no cached answer,
  and `FULL_EVAL_MAX_CALLS=0`) come back as `{id, category, question, skipped}` with no `retrieved` list, which the
  schema refused. Fixed: skipped entries are accepted and shown as skipped with the reason, the report says how many
  were skipped, and a result that fails its schema now says "Unexpected response from the server". Redeployed;
  the check passed.
- **Why 3 questions were skipped (m1, m2, x1):** see "Known issue" below.

## Known issue: uploads change the BM25 scores of other codebases

BM25's document count and term frequencies are computed over **every** indexed codebase, not only the ones searched.
While an upload exists (here, a user's `auction-checklist`), the keyword scores of the sample codebases shift slightly.
For some questions this reorders the retrieved chunks, so the prompt differs from the cached one:

- a suggested question can cost a real call instead of 0 (the three asked by the E2E were still cache hits);
- a full replay skips the questions whose answers are no longer cached.

It resolves itself when the uploads expire (24 h). The proper fix is per-search BM25 statistics (only the selected
codebases), but that changes every sample ranking and invalidates the answer cache, so it needs a new full evaluation
(~50 real calls). Left for a later session.

## Redeploy

```bash
npm run typecheck && npm run lint && npm test && npm run test:e2e
vercel --prod --yes
BASE_URL=https://taller-codebase-rag.vercel.app npm run test:e2e   # ~1 real call (the new question in E1)
```

Changing the backend URL needs a rebuild (`vercel env rm/add`, then `vercel --prod`). A new frontend domain must be
added to `FRONTEND_ORIGIN` on Railway.
