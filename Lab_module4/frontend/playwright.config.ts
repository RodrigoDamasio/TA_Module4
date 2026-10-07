import { defineConfig, devices } from "@playwright/test";

// BASE_URL=https://<vercel-domain> runs the production subset (E9) instead of local servers.
const deployedUrl = process.env.BASE_URL;

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  workers: 1, // one backend: index jobs run one at a time
  use: {
    baseURL: deployedUrl ?? "http://localhost:3000",
    // Playwright's bundled Chromium is not supported on Ubuntu 20.04: use the installed Chrome.
    channel: "chrome",
    trace: "retain-on-failure",
  },
  projects: [{ name: "desktop", use: { ...devices["Desktop Chrome"], channel: "chrome" } }],
  webServer: deployedUrl
    ? undefined
    : [
        {
          // Real backend, fake embedder and fake LLM: the whole pipeline, 0 quota, fast.
          // RERANK_MODEL="" mirrors production (reranker off).
          command: "rm -rf .e2e && mkdir -p .e2e && ../../../.venv/bin/uvicorn app.main:app --port 8000",
          cwd: "../backend",
          url: "http://localhost:8000/health",
          env: {
            LLM_MODE: "fake",
            EMBED_MODE: "fake",
            RERANK_MODEL: "",
            DATABASE_PATH: ".e2e/rag.db",
            CHROMA_PATH: ".e2e/chroma",
            FULL_EVAL_MAX_CALLS: "100",
            FRONTEND_ORIGIN: "http://localhost:3000",
            RATE_LIMIT_QUERY_PER_MINUTE: "1000",
            RATE_LIMIT_QUERY_PER_DAY: "10000",
            RATE_LIMIT_INDEX_PER_MINUTE: "1000",
            RATE_LIMIT_INDEX_PER_DAY: "10000",
            RATE_LIMIT_SEARCH_PER_MINUTE: "1000",
          },
          reuseExistingServer: false,
        },
        {
          // Production build: no file watchers (the dev server hits the OS watch limit here).
          command: "npm run build && npm run start",
          url: "http://localhost:3000",
          env: { NEXT_PUBLIC_API_URL: "http://localhost:8000" },
          timeout: 180_000,
          reuseExistingServer: false,
        },
      ],
});
