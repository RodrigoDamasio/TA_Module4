"use client";
import { useEffect, useState } from "react";
import Badge from "@/components/Badge";
import { citedNumbers } from "@/lib/citations";
import { modeLabel } from "@/lib/format";
import AnswerText from "./AnswerText";
import PipelineView from "./PipelineView";
import SourceCard from "./SourceCard";
import TraceBar from "./TraceBar";
import { isQueryResult, type Turn } from "./types";

export default function TurnView({ turn }: { turn: Turn }) {
  const [flash, setFlash] = useState<number | null>(null);

  useEffect(() => {
    if (flash === null) return;
    const timer = setTimeout(() => setFlash(null), 2000);
    return () => clearTimeout(timer);
  }, [flash]);

  const sourceId = (n: number) => `${turn.id}-src-${n}`;
  function cite(n: number) {
    const el = document.getElementById(sourceId(n));
    if (el instanceof HTMLDetailsElement) el.open = true;
    el?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
    el?.focus();
    setFlash(n);
  }

  const result = turn.result;
  const sources = result ? (isQueryResult(result) ? result.sources : result.hits) : [];
  const cited = result && isQueryResult(result) ? citedNumbers(result.answer) : [];
  const ordered = [...sources].sort(
    (a, b) => Number(cited.includes(b.n)) - Number(cited.includes(a.n)) || a.n - b.n,
  );
  const finalIds = new Set(sources.map((s) => s.chunk_id));

  return (
    <article aria-label={`Question: ${turn.question}`} className="space-y-3">
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-lg bg-zinc-100 px-3 py-2 dark:bg-zinc-800">
          <p className="whitespace-pre-wrap">{turn.question}</p>
          <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-400">
            {turn.kind === "search" ? "Search only" : "Ask"} · {turn.params.codebases.join(", ")} ·{" "}
            {modeLabel(turn.params.mode)} · K {turn.params.k}
          </p>
        </div>
      </div>

      {turn.status === "pending" && (
        <p className="text-sm text-zinc-600 dark:text-zinc-400" aria-busy="true">
          {turn.kind === "search" ? "Searching the code…" : "Searching the code and writing the answer…"}
        </p>
      )}
      {turn.status === "error" && (
        <p className="text-sm text-red-800 dark:text-red-300">Not answered: {turn.error}</p>
      )}

      {result && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div className="space-y-3">
            {isQueryResult(result) ? (
              <div className="space-y-2">
                {!result.found && (
                  <p className="rounded-md border border-zinc-300 bg-zinc-50 p-2 text-sm dark:border-zinc-700 dark:bg-zinc-900">
                    <Badge>not found</Badge> The indexed code doesn&apos;t answer this. The excerpts that were checked are listed.
                  </p>
                )}
                {!result.grounded && <Badge tone="warn">Citations could not be verified</Badge>}
                <AnswerText text={result.answer} sources={result.sources} onCite={cite} />
              </div>
            ) : (
              <p className="text-sm">
                {result.hits.length} chunks found. Search only: no answer is written, no AI call is made.
              </p>
            )}
            <TraceBar trace={result.trace} meta={result.meta} requestedMode={turn.params.mode} />
            {result.pipeline && <PipelineView pipeline={result.pipeline} finalIds={finalIds} />}
          </div>
          <section aria-label="Sources" className="space-y-2">
            <h3 className="text-sm font-semibold">Sources</h3>
            {ordered.length === 0 && <p className="text-sm">No chunks matched.</p>}
            {ordered.map((s) => (
              <SourceCard key={s.chunk_id} source={s} domId={sourceId(s.n)} cited={cited.includes(s.n)} flash={flash === s.n} />
            ))}
          </section>
        </div>
      )}
    </article>
  );
}
