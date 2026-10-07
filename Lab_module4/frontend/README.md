# Codebase RAG — frontend

Next.js 16 UI for the Codebase RAG API ([../backend](../backend)). Design: [FRONTEND_PLAN.md](../FRONTEND_PLAN.md).

| Page | What it does |
|---|---|
| **Ask** (`/`) | Chat about the indexed code. Answers have `[n]` citations linked to source cards (path, lines, code, vector / BM25 / RRF scores and ranks), a trace bar with the time of each step, cache badges, and "How this answer was made": every step from the question to the exact prompt and the raw model output. *Search only* finds the code without calling the AI. Suggested questions come from the evaluation dataset and are answered from the server's cache |
| **Codebases** (`/codebases`) | The indexed codebases (two read-only samples, uploads expire after 24 h). Upload files or a whole folder: the browser applies the server's rules (file types, dependency folders, lockfiles, secrets, limits from `GET /config`), shows what is skipped and why, and sends the files in batches as background index jobs |
| **Codebase** (`/codebases/[id]`) | Files, and the chunks each file was split into |
| **Evaluation** (`/evaluation`) | The stored full report (retrieval metrics, judge scores, deterministic checks, judge sanity check, per question), the 72-row comparison grid, runs (retrieval, full replay, your own dataset) and server stats. All at 0 AI calls on the deployed server |

## Run locally

Node 24 (`source ~/.nvm/nvm.sh && nvm use 24`). The backend must run on port 8000.

```bash
npm install
npm run build && npm run start      # http://localhost:3000 (`next dev` hits the OS file-watch limit here)
```

`NEXT_PUBLIC_API_URL` (default `http://localhost:8000`) is read at **build** time.

## Tests

```bash
npm run typecheck && npm run lint
npm test                 # Vitest: unit + component, 0 AI calls
npm run test:coverage    # ≥ 80 % lines, branches, functions, statements
npm run test:e2e         # Playwright: starts the real backend with a fake LLM and fake embedder, 0 AI calls
BASE_URL=https://<vercel-domain> npm run test:e2e   # production subset (about 1 real AI call)
```

E2E uses the installed Google Chrome (`channel: "chrome"`): Playwright's own Chromium is not supported on Ubuntu 20.04.

| Suite | Count |
|---|---|
| Unit + component (Vitest) | 94 tests, ~95 % statements |
| E2E local (Playwright) | 8 tests: upload a folder, ask with citations, pipeline view, search across two codebases, evaluation runs, error handling (network, 429 countdown, quota → search), 375 px layout, axe |

`tests/fixtures/` holds real API responses (a local fake backend, plus the stored reports and one cached real answer from production), so the Zod schemas are tested against what the server really sends.

## Structure

```
app/          pages (server components pass URL params to client components)
components/   ask/ · codebases/ · evaluation/ · shared pieces (Badge, CodeBlock, Tabs, ErrorBanner…)
hooks/        useLoad · useApiError (+ Retry-After countdown) · useCountdown · useNow
lib/          schemas.ts (Zod) · api.ts (ApiError kinds from RFC 9457 slugs) · upload.ts (server rules) ·
              indexing.ts (batches + job polling) · citations.ts · dropped.ts · slug.ts · template.ts · format.ts
```
