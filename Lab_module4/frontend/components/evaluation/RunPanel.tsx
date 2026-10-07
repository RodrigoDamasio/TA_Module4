"use client";
import { useState } from "react";
import ErrorBanner from "@/components/ErrorBanner";
import { useApiError } from "@/hooks/useApiError";
import { ApiError, runFull, runRetrieval } from "@/lib/api";
import { modeLabel } from "@/lib/format";
import { followJob } from "@/lib/indexing";
import { type Config, EvalProgressSchema, type Report, ReportSchema, type SearchMode } from "@/lib/schemas";
import { DATASET_TEMPLATE, parseDataset } from "@/lib/template";
import ReportView from "./ReportView";

type Busy = null | "retrieval" | "full" | "custom";

function download(name: string, text: string) {
  if (typeof URL.createObjectURL !== "function") return;
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export default function RunPanel({ config }: { config: Config }) {
  const [k, setK] = useState(config.defaults.k);
  const [mode, setMode] = useState<SearchMode>(config.defaults.mode);
  const [busy, setBusy] = useState<Busy>(null);
  const [progress, setProgress] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [custom, setCustom] = useState("");
  const [customError, setCustomError] = useState<string | null>(null);
  const { error, cooldown, fail, clear } = useApiError();

  async function go(kind: Exclude<Busy, null>, work: () => Promise<Report>) {
    setBusy(kind);
    setReport(null);
    setProgress("");
    clear();
    try {
      setReport(await work());
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  const retrieval = () => go("retrieval", () => runRetrieval({ k, search_mode: mode }));

  const full = () =>
    go("full", async () => {
      const job = await followJob(await runFull(), (j) => {
        const p = EvalProgressSchema.safeParse(j.progress);
        if (p.success) setProgress(`${p.data.examples_done} of ${p.data.examples_total} questions · ${p.data.real_calls ?? 0} real AI calls, ${p.data.cached_calls ?? 0} from cache`);
      });
      if (job.status === "failed") throw new ApiError("server", job.error?.detail ?? "The evaluation failed.");
      const report = ReportSchema.safeParse(job.result);
      if (!report.success) throw new ApiError("invalid_response", "Unexpected response from the server.");
      return report.data;
    });

  function runCustom() {
    const parsed = parseDataset(custom, config.limits.max_custom_examples);
    if ("error" in parsed) {
      setCustomError(parsed.error);
      return;
    }
    setCustomError(null);
    void go("custom", () => runRetrieval({ k, search_mode: mode, examples: parsed.examples }));
  }

  return (
    <div className="space-y-6">
      <p className="text-sm text-zinc-600 dark:text-zinc-400">All of these cost 0 AI calls on this server.</p>
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <label htmlFor="run-k" className="block text-xs font-medium">K</label>
          <select id="run-k" value={k} onChange={(e) => setK(Number(e.target.value))} className="rounded border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900">
            {Array.from({ length: config.limits.max_k }, (_, i) => i + 1).map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </div>
        <div className="space-y-1">
          <label htmlFor="run-mode" className="block text-xs font-medium">Search mode</label>
          <select id="run-mode" value={mode} onChange={(e) => setMode(e.target.value as SearchMode)} className="rounded border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900">
            {config.modes.map((m) => <option key={m.id} value={m.id} disabled={!m.available}>{modeLabel(m.id)}{m.available ? "" : " (unavailable)"}</option>)}
          </select>
        </div>
        <button type="button" disabled={busy !== null || cooldown > 0} aria-busy={busy === "retrieval"} onClick={() => void retrieval()} className="rounded-md bg-orange-700 px-4 py-1.5 text-sm font-medium text-white hover:bg-orange-800 disabled:bg-zinc-400 dark:disabled:bg-zinc-700">
          Run retrieval evaluation
        </button>
        <button type="button" disabled={busy !== null || cooldown > 0} aria-busy={busy === "full"} onClick={() => void full()} className="rounded-md border border-orange-700 px-4 py-1.5 text-sm font-medium text-orange-800 disabled:border-zinc-400 disabled:text-zinc-500 dark:text-orange-300">
          Replay full evaluation
        </button>
      </div>
      <p className="text-xs text-zinc-600 dark:text-zinc-400">
        Retrieval: the 20 built-in questions, searched with these settings (a few seconds). Full: answers and judge
        scores, replayed from the server&apos;s cache with the default settings.
      </p>

      <details className="space-y-2">
        <summary className="cursor-pointer text-sm font-medium">Your own dataset (retrieval only)</summary>
        <div className="space-y-2 pt-2">
          <p className="text-xs text-zinc-600 dark:text-zinc-400">
            A JSON list of 1 to {config.limits.max_custom_examples} examples. Each one names the codebase, file and symbol
            that answer it; the server finds their lines.{" "}
            <button type="button" className="font-medium text-orange-800 underline dark:text-orange-300" onClick={() => download("dataset-template.json", JSON.stringify(DATASET_TEMPLATE, null, 2))}>
              Download a template
            </button>{" "}
            <button type="button" className="font-medium text-orange-800 underline dark:text-orange-300" onClick={() => setCustom(JSON.stringify(DATASET_TEMPLATE, null, 2))}>
              Paste the template
            </button>
          </p>
          <label htmlFor="custom-dataset" className="sr-only">Custom dataset JSON</label>
          <textarea id="custom-dataset" rows={8} value={custom} onChange={(e) => setCustom(e.target.value)} className="w-full rounded border border-zinc-300 bg-white p-2 font-mono text-xs dark:border-zinc-700 dark:bg-zinc-900" />
          <input type="file" accept="application/json,.json" aria-label="Load a dataset file" className="text-xs" onChange={(e) => { const f = e.target.files?.[0]; if (f) void f.text().then(setCustom); }} />
          {customError && <p role="alert" className="text-sm text-red-800 dark:text-red-300">{customError}</p>}
          <button type="button" disabled={busy !== null || !custom.trim()} aria-busy={busy === "custom"} onClick={runCustom} className="rounded-md bg-orange-700 px-4 py-1.5 text-sm font-medium text-white disabled:bg-zinc-400 dark:disabled:bg-zinc-700">
            Run on my dataset
          </button>
        </div>
      </details>

      <div role="status" aria-live="polite" className="text-sm">
        {busy && (busy === "full" ? `Replaying the full evaluation… ${progress}` : "Running the retrieval evaluation…")}
      </div>
      {error && <ErrorBanner error={error} cooldown={cooldown} />}
      {report && <ReportView report={report} />}
    </div>
  );
}
