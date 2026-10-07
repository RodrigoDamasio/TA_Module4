"use client";
import ErrorBanner from "@/components/ErrorBanner";
import { useLoad } from "@/hooks/useLoad";
import { stats } from "@/lib/api";
import { formatMs, percent } from "@/lib/format";

export default function StatsView() {
  const { data, error, reload } = useLoad(stats);
  if (error) return <ErrorBanner error={error} cooldown={0} actions={[{ label: "Retry", onClick: reload }]} />;
  if (!data) return <p className="text-sm">Loading…</p>;
  const l = data.llm;
  return (
    <div className="space-y-4 text-sm">
      <div className="flex items-center justify-between">
        <p className="text-zinc-600 dark:text-zinc-400">Since the server started · {data.window}</p>
        <button type="button" onClick={reload} className="font-medium text-orange-800 underline dark:text-orange-300">Refresh</button>
      </div>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          ["Real AI calls today", `${l.calls_today} of ${l.daily_limit}`],
          ["Answers from cache", String(l.cached_today)],
          ["Cache hit rate", percent(l.cache_hit_rate)],
          ["Tokens in / out", `${l.input_tokens} / ${l.output_tokens}`],
          ["Paid-tier equivalent", `$${l.paid_equivalent_usd.toFixed(4)}`],
          ["Requests", Object.entries(data.requests).map(([k, v]) => `${k} ${v}`).join(", ") || "none"],
          ["Codebases / chunks", `${data.index.codebases ?? "—"} / ${data.index.chunks ?? "—"}`],
          ["Embedding cache hit rate", percent(data.index.embedding_cache_hit_rate)],
        ].map(([k, v]) => (
          <div key={k} className="rounded-md border border-zinc-200 p-3 dark:border-zinc-800">
            <dt className="text-xs text-zinc-600 dark:text-zinc-400">{k}</dt>
            <dd className="font-semibold">{v}</dd>
          </div>
        ))}
      </dl>
      <table className="text-left">
        <caption className="mb-1 text-left font-semibold">Time per step (search and questions)</caption>
        <thead className="text-xs text-zinc-600 dark:text-zinc-400">
          <tr><th scope="col" className="pr-6">Step</th><th scope="col" className="pr-6">p50</th><th scope="col">p95</th></tr>
        </thead>
        <tbody>
          {Object.entries(data.latency_ms).map(([step, v]) => (
            <tr key={step}>
              <th scope="row" className="pr-6 font-mono font-normal">{step}</th>
              <td className="pr-6 tabular-nums">{v.p50 === null ? "—" : formatMs(v.p50)}</td>
              <td className="tabular-nums">{v.p95 === null ? "—" : formatMs(v.p95)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-xs text-zinc-600 dark:text-zinc-400">Counters reset when the server restarts.</p>
    </div>
  );
}
