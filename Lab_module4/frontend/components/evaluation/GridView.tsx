"use client";
import { useState } from "react";
import Badge from "@/components/Badge";
import { formatMs, metric, modeLabel } from "@/lib/format";
import type { GridReport, GridRow } from "@/lib/schemas";

const STRATEGIES: Record<string, string> = {
  code_aware: "Code-aware + header",
  code_aware_no_header: "Code-aware, no header",
  fixed: "Fixed-size (500 chars)",
};

type SortKey = "precision" | "recall" | "mrr" | "ndcg" | "context_chars" | "latency_p50_ms";
const SORTS: { key: SortKey; label: string }[] = [
  { key: "recall", label: "Recall" },
  { key: "mrr", label: "MRR" },
  { key: "ndcg", label: "nDCG" },
  { key: "precision", label: "Precision" },
  { key: "context_chars", label: "Context chars" },
  { key: "latency_p50_ms", label: "Latency p50" },
];

const shortModel = (m: string) => m.split("/").pop() ?? m;

function Filter({ label, value, options, onChange, show = (v) => v }: {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
  show?: (v: string) => string;
}) {
  const id = `grid-${label.toLowerCase()}`;
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-xs font-medium">{label}</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className="rounded border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900">
        <option value="">All</option>
        {options.map((o) => <option key={o} value={o}>{show(o)}</option>)}
      </select>
    </div>
  );
}

export default function GridView({ grid }: { grid: GridReport }) {
  const [embedder, setEmbedder] = useState("");
  const [strategy, setStrategy] = useState("");
  const [mode, setMode] = useState("");
  const [k, setK] = useState("5");
  const [sort, setSort] = useState<SortKey>("mrr");
  const best = grid.summary.best_at_5;
  const unique = (f: (r: GridRow) => string) => [...new Set(grid.rows.map(f))];
  const isBest = (r: GridRow) => r.embedder === best.embedder && r.strategy === best.strategy && r.mode === best.mode && r.k === 5;

  const rows = grid.rows
    .filter((r) => (!embedder || r.embedder === embedder) && (!strategy || r.strategy === strategy) && (!mode || r.mode === mode) && (!k || String(r.k) === k))
    .sort((a, b) => (sort === "context_chars" || sort === "latency_p50_ms" ? a[sort] - b[sort] : b[sort] - a[sort]));

  return (
    <div className="space-y-4">
      <p className="text-sm">
        Every combination of chunking strategy, embedding model, search mode and K, measured on the same {grid.n_examples} questions
        with 0 AI calls. Best at K 5: <strong>{STRATEGIES[best.strategy] ?? best.strategy}</strong>, {shortModel(best.embedder)},{" "}
        {modeLabel(best.mode)} (recall {metric(best.recall)}, MRR {metric(best.mrr)}): the configuration this server uses.
      </p>
      <div className="flex flex-wrap gap-3">
        <Filter label="Chunking" value={strategy} options={unique((r) => r.strategy)} onChange={setStrategy} show={(v) => STRATEGIES[v] ?? v} />
        <Filter label="Embedder" value={embedder} options={unique((r) => r.embedder)} onChange={setEmbedder} show={shortModel} />
        <Filter label="Mode" value={mode} options={unique((r) => r.mode)} onChange={setMode} show={modeLabel} />
        <Filter label="K" value={k} options={unique((r) => String(r.k)).sort((a, b) => Number(a) - Number(b))} onChange={setK} />
        <div className="space-y-1">
          <label htmlFor="grid-sort" className="block text-xs font-medium">Sort by</label>
          <select id="grid-sort" value={sort} onChange={(e) => setSort(e.target.value as SortKey)} className="rounded border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900">
            {SORTS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
        </div>
      </div>
      <p role="status" className="text-xs text-zinc-600 dark:text-zinc-400">{rows.length} of {grid.rows.length} rows</p>
      <div role="region" aria-label="Comparison grid" tabIndex={0} className="max-h-[36rem] overflow-auto rounded border border-zinc-200 dark:border-zinc-800">
        <table className="w-full min-w-[44rem] text-left text-sm">
          <caption className="sr-only">Retrieval metrics for each configuration</caption>
          <thead className="sticky top-0 bg-zinc-100 text-xs dark:bg-zinc-900">
            <tr>
              {["Chunking", "Embedder", "Mode", "K", "Chunks", "Precision", "Recall", "MRR", "nDCG", "Context chars", "Latency p50"].map((h) => (
                <th key={h} scope="col" className="px-2 py-1 whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.embedder}-${r.strategy}-${r.mode}-${r.k}`} className={`border-t border-zinc-200 dark:border-zinc-800 ${isBest(r) ? "bg-orange-50 dark:bg-orange-950" : ""}`}>
                <td className="px-2 py-1">
                  {STRATEGIES[r.strategy] ?? r.strategy} {isBest(r) && <Badge tone="accent">server default</Badge>}
                </td>
                <td className="px-2 py-1 text-xs">{shortModel(r.embedder)}</td>
                <td className="px-2 py-1">{modeLabel(r.mode)}</td>
                <td className="px-2 py-1 tabular-nums">{r.k}</td>
                <td className="px-2 py-1 tabular-nums">{r.chunks}</td>
                <td className="px-2 py-1 tabular-nums">{metric(r.precision)}</td>
                <td className="px-2 py-1 tabular-nums">{metric(r.recall)}</td>
                <td className="px-2 py-1 tabular-nums">{metric(r.mrr)}</td>
                <td className="px-2 py-1 tabular-nums">{metric(r.ndcg)}</td>
                <td className="px-2 py-1 tabular-nums">{r.context_chars.toLocaleString("en")}</td>
                <td className="px-2 py-1 tabular-nums whitespace-nowrap">{formatMs(r.latency_p50_ms)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
