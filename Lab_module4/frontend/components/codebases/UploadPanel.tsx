"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import Badge from "@/components/Badge";
import { fromDrop } from "@/lib/dropped";
import { formatBytes } from "@/lib/format";
import { BatchFailed, type BatchUpdate, indexAll, type Totals } from "@/lib/indexing";
import type { Codebase, Config } from "@/lib/schemas";
import { nameError, suggestName } from "@/lib/slug";
import { batches, type Candidate, fromFiles, type Review, review, SKIP_LABELS } from "@/lib/upload";

type Phase =
  | { name: "idle" }
  | { name: "indexing"; update: BatchUpdate | null }
  | { name: "done"; totals: Totals; codebase: string }
  | { name: "failed"; batch: number; message: string; totals: Totals };

export default function UploadPanel({
  config,
  codebases,
  onIndexed,
}: {
  config: Config;
  codebases: Codebase[];
  onIndexed: () => void;
}) {
  const [name, setName] = useState("");
  const [nameTouched, setNameTouched] = useState(false);
  const [result, setResult] = useState<Review | null>(null);
  const [reading, setReading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [phase, setPhase] = useState<Phase>({ name: "idle" });
  const filesInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    folderInput.current?.setAttribute("webkitdirectory", ""); // not in React's types
  }, []);

  const samples = codebases.filter((c) => c.read_only).map((c) => c.id);
  const existing = codebases.find((c) => c.id === name && !c.read_only);
  const nameProblem = nameError(name, config.files.codebase_id_pattern, samples);
  const indexing = phase.name === "indexing";
  const plan = result ? batches(result.accepted, config) : [];

  let blocked: string | null = null;
  if (!result || result.accepted.length === 0) blocked = "Choose files or a folder first.";
  else if (result.problems.length > 0) blocked = result.problems[0];
  else if (nameProblem) blocked = nameProblem;

  async function load(candidates: Candidate[], folder: string | null) {
    setReading(true);
    setPhase({ name: "idle" });
    try {
      setResult(await review(candidates, config));
      if (folder && !nameTouched) setName(suggestName(folder));
    } finally {
      setReading(false);
    }
  }

  function onPicked(files: FileList | null) {
    if (!files || files.length === 0) return;
    const list = Array.from(files);
    const rel = (list[0] as File & { webkitRelativePath?: string }).webkitRelativePath;
    const folder = rel && rel.includes("/") ? rel.split("/")[0] : null;
    void load(fromFiles(list), folder);
  }

  async function run(start = 0, totals?: Totals) {
    if (!result) return;
    setPhase({ name: "indexing", update: null });
    try {
      const sum = await indexAll(name, plan, (update) => setPhase({ name: "indexing", update }), { start, totals });
      setPhase({ name: "done", totals: sum, codebase: name });
      onIndexed();
    } catch (err) {
      if (err instanceof BatchFailed) {
        setPhase({ name: "failed", batch: err.batch, message: err.message, totals: err.totals });
        if (err.batch > 0) onIndexed();
      } else {
        throw err;
      }
    }
  }

  const skippedServer = phase.name === "done" ? phase.totals.skipped : [];

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <label htmlFor="codebase-name" className="block text-sm font-medium">
          Codebase name
        </label>
        <input
          id="codebase-name"
          value={name}
          maxLength={40}
          disabled={indexing}
          onChange={(e) => {
            setNameTouched(true);
            setName(e.target.value);
          }}
          placeholder="my-project"
          aria-describedby="name-hint"
          className="w-full rounded border border-zinc-300 bg-white px-2 py-1 font-mono text-sm dark:border-zinc-700 dark:bg-zinc-900"
        />
        <p id="name-hint" className="text-xs text-zinc-600 dark:text-zinc-400">
          {name && nameProblem
            ? nameProblem
            : existing
              ? `${name} exists: it will be re-indexed, and unchanged files are skipped.`
              : "Lowercase letters, digits and '-'. Suggested from the folder name."}
        </p>
      </div>

      <button
        type="button"
        disabled={indexing}
        onClick={() => filesInput.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const data = e.dataTransfer;
          void fromDrop(data).then(({ candidates, folder }) => load(candidates, folder));
        }}
        className={`flex w-full flex-col items-center gap-1 rounded-md border-2 border-dashed p-6 text-sm ${
          dragging ? "border-orange-600 bg-orange-50 dark:bg-orange-950" : "border-zinc-300 dark:border-zinc-700"
        }`}
      >
        <span className="font-medium">Drop files or a folder here</span>
        <span className="text-zinc-600 dark:text-zinc-400">or click to choose files</span>
      </button>
      <div className="flex flex-wrap gap-3 text-sm">
        <button type="button" disabled={indexing} onClick={() => folderInput.current?.click()} className="font-medium text-orange-800 underline dark:text-orange-300">
          Choose a folder
        </button>
        {result && !indexing && (
          <button type="button" onClick={() => { setResult(null); setPhase({ name: "idle" }); }} className="underline">
            Clear
          </button>
        )}
      </div>
      <input ref={filesInput} type="file" multiple hidden aria-label="Choose files" data-testid="files-input" onChange={(e) => { onPicked(e.target.files); e.target.value = ""; }} />
      <input ref={folderInput} type="file" multiple hidden aria-label="Choose a folder" data-testid="folder-input" onChange={(e) => { onPicked(e.target.files); e.target.value = ""; }} />

      {reading && <p role="status" className="text-sm">Reading files…</p>}

      {result && (
        <div className="space-y-2">
          <p role="status" className="text-sm">
            {result.accepted.length} files accepted, {result.skipped.length} skipped
            {result.dependencyFiles > 0 && ` (+${result.dependencyFiles} in dependency or build folders)`},{" "}
            {formatBytes(result.totalBytes)} of {formatBytes(config.limits.max_bytes_per_codebase)}
            {plan.length > 1 && `, sent in ${plan.length} requests`}.
          </p>
          {result.problems.map((p) => (
            <p key={p} className="text-sm text-red-800 dark:text-red-300">{p}</p>
          ))}
          {result.accepted.length > 0 && (
            <div role="region" aria-label="Files to index" tabIndex={0} className="max-h-56 overflow-auto rounded border border-zinc-200 dark:border-zinc-800">
              <table className="w-full text-left text-xs">
                <caption className="sr-only">Files to index</caption>
                <thead className="sticky top-0 bg-zinc-100 dark:bg-zinc-900">
                  <tr><th scope="col" className="px-2 py-1">Path</th><th scope="col" className="px-2 py-1 text-right">Size</th></tr>
                </thead>
                <tbody>
                  {result.accepted.map((f) => (
                    <tr key={f.path} className="border-t border-zinc-200 dark:border-zinc-800">
                      <td className="px-2 py-1 font-mono break-all">{f.path}</td>
                      <td className="px-2 py-1 text-right whitespace-nowrap">{formatBytes(f.bytes)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {result.skipped.length > 0 && (
            <details className="text-sm">
              <summary className="cursor-pointer">Skipped files ({result.skipped.length})</summary>
              <ul className="mt-1 space-y-0.5 text-xs">
                {result.skipped.map((s) => (
                  <li key={s.path}>
                    <span className="font-mono break-all">{s.path}</span>: {SKIP_LABELS[s.reason]}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      <div className="space-y-2">
        <button
          type="button"
          disabled={blocked !== null || indexing}
          aria-busy={indexing}
          onClick={() => void run()}
          className="rounded-md bg-orange-700 px-4 py-1.5 text-sm font-medium text-white hover:bg-orange-800 disabled:bg-zinc-400 dark:disabled:bg-zinc-700"
        >
          Index
        </button>
        {blocked && result && <p className="text-xs text-zinc-600 dark:text-zinc-400">{blocked}</p>}
      </div>

      <div role="status" aria-live="polite" className="text-sm">
        {phase.name === "indexing" && (
          <p>
            {phase.update
              ? `Request ${phase.update.batch + 1} of ${phase.update.batches}` +
                (phase.update.progress
                  ? ` · ${phase.update.progress.files_done} of ${phase.update.progress.files_total} files · ${phase.update.progress.chunks} chunks · ${phase.update.progress.cache_hits} from cache`
                  : " · starting…")
              : "Starting…"}
          </p>
        )}
        {phase.name === "done" && (
          <div className="space-y-1 rounded-md border border-emerald-300 bg-emerald-50 p-3 dark:border-emerald-800 dark:bg-emerald-950">
            <p className="font-medium">
              <Badge tone="good">done</Badge> {phase.codebase}: {phase.totals.files_indexed} files indexed
              {phase.totals.files_unchanged > 0 && `, ${phase.totals.files_unchanged} unchanged`}, {phase.totals.chunks_added} chunks added
              {phase.totals.embedding_cache_hits > 0 && ` (${phase.totals.embedding_cache_hits} embeddings from cache)`}.
            </p>
            {skippedServer.length > 0 && (
              <p className="text-xs">
                Skipped by the server: {skippedServer.map((s) => `${s.path} (${s.reason})`).join(", ")}
              </p>
            )}
            <p className="flex gap-3">
              <Link href={`/codebases/${encodeURIComponent(phase.codebase)}`} className="font-medium text-orange-800 underline dark:text-orange-300">
                See its files and chunks
              </Link>
              <Link href={`/?cb=${encodeURIComponent(phase.codebase)}`} className="font-medium text-orange-800 underline dark:text-orange-300">
                Ask about it
              </Link>
            </p>
          </div>
        )}
      </div>
      {phase.name === "failed" && (
        <div role="alert" className="space-y-1 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-100">
          <p className="font-medium">
            Request {phase.batch + 1} of {plan.length} failed: {phase.message}
          </p>
          {phase.batch > 0 && <p>The files of the earlier requests are indexed.</p>}
          <button type="button" onClick={() => void run(phase.batch, phase.totals)} className="font-medium underline">
            Retry from request {phase.batch + 1}
          </button>
        </div>
      )}
    </div>
  );
}
