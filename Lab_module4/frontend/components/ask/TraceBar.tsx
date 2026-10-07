import Badge from "@/components/Badge";
import { formatMs, modeLabel } from "@/lib/format";
import type { Meta, SearchMode, Trace } from "@/lib/schemas";

const COLORS = ["bg-orange-600", "bg-sky-600", "bg-emerald-600", "bg-violet-600", "bg-amber-500", "bg-rose-600", "bg-zinc-500"];

const numberAttr = (v: unknown): number | null => (typeof v === "number" ? v : null);

export default function TraceBar({
  trace,
  meta,
  requestedMode,
}: {
  trace: Trace;
  meta: Meta;
  requestedMode: SearchMode;
}) {
  const total = trace.spans.reduce((sum, s) => sum + s.ms, 0) || 1;
  const generate = trace.spans.find((s) => s.name === "generate");
  const tokensIn = numberAttr(generate?.input_tokens);
  const tokensOut = numberAttr(generate?.output_tokens);
  const embedCached = trace.cache?.query_embedding ?? trace.spans.find((s) => s.name === "embed_query")?.cached === true;
  return (
    <div className="space-y-2 text-xs text-zinc-600 dark:text-zinc-400">
      <div className="flex h-2 overflow-hidden rounded" aria-hidden="true">
        {trace.spans.map((s, i) => (
          <span key={s.name} className={COLORS[i % COLORS.length]} style={{ width: `${(s.ms / total) * 100}%` }} />
        ))}
      </div>
      <ul className="flex flex-wrap gap-x-3 gap-y-1" aria-label="Time per step">
        {trace.spans.map((s, i) => (
          <li key={s.name} className="flex items-center gap-1">
            <span aria-hidden="true" className={`inline-block h-2 w-2 rounded-sm ${COLORS[i % COLORS.length]}`} />
            <span className="font-mono">{s.name}</span> {formatMs(s.ms)}
            {!s.ok && <Badge tone="bad">failed</Badge>}
          </li>
        ))}
        <li className="font-medium text-zinc-800 dark:text-zinc-200">total {formatMs(trace.total_ms)}</li>
      </ul>
      <div className="flex flex-wrap items-center gap-2">
        {trace.cache?.llm && <Badge tone="good">answer from cache (0 AI calls)</Badge>}
        {embedCached && <Badge tone="good">query embedding cached</Badge>}
        {tokensIn !== null && (
          <span>
            tokens {tokensIn} in / {tokensOut ?? 0} out
          </span>
        )}
      </div>
      <p>
        {meta.model} · prompt v{meta.prompt_version} · {meta.embedder} · chunker v{meta.chunker_version} ·{" "}
        {modeLabel(meta.mode)} · K {meta.k} · <span className="font-mono">{trace.request_id}</span>
      </p>
      {meta.mode !== requestedMode && (
        <p>
          Asked for {modeLabel(requestedMode)}, ran as {modeLabel(meta.mode)}
          {requestedMode === "hybrid_rerank" && !meta.reranker ? " (the reranker is turned off on this server)." : "."}
        </p>
      )}
    </div>
  );
}
