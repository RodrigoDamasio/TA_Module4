"use client";
import { useState } from "react";
import Badge from "@/components/Badge";
import CodeBlock from "@/components/CodeBlock";
import { formatMs, lineRange } from "@/lib/format";
import type { Candidate, Pipeline } from "@/lib/schemas";

const SKIP_REASONS: Record<string, string> = {
  disabled: "Not run: the reranker is turned off on this server (memory limit).",
  "mode=hybrid": "Not run: this mode doesn't rerank.",
  loading: "Not run: the reranker is still loading.",
  unavailable: "Not run: the reranker is unavailable.",
};

interface Column {
  label: string;
  value: (c: Candidate) => React.ReactNode;
}

const num = (v: unknown, digits = 3) => (typeof v === "number" ? v.toFixed(digits) : "—");
const rank = (v: unknown) => (typeof v === "number" ? v : "—");

function location(c: Candidate) {
  if (!c.path) return <span className="font-mono">{c.chunk_id}</span>;
  const lines = c.start_line !== undefined && c.end_line !== undefined ? `:${lineRange(c.start_line, c.end_line)}` : "";
  return (
    <span>
      <span className="font-mono break-all">
        {c.codebase}/{c.path}
        {lines}
      </span>
      {c.symbol && <span className="block text-zinc-600 dark:text-zinc-400">{c.symbol}</span>}
    </span>
  );
}

function CandidateTable({
  rows,
  columns,
  label,
  finalIds,
}: {
  rows: Candidate[];
  columns: Column[];
  label: string;
  finalIds: Set<string>;
}) {
  if (rows.length === 0) return <p className="text-sm text-zinc-600 dark:text-zinc-400">No candidates.</p>;
  return (
    <div role="region" aria-label={label} tabIndex={0} className="max-h-72 overflow-auto rounded border border-zinc-200 dark:border-zinc-800">
      <table className="w-full text-left text-xs">
        <caption className="sr-only">{label}</caption>
        <thead className="sticky top-0 bg-zinc-100 dark:bg-zinc-900">
          <tr>
            <th scope="col" className="px-2 py-1">#</th>
            <th scope="col" className="px-2 py-1">Chunk</th>
            {columns.map((c) => (
              <th key={c.label} scope="col" className="px-2 py-1 whitespace-nowrap">{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.chunk_id} className="border-t border-zinc-200 align-top dark:border-zinc-800">
              <td className="px-2 py-1 font-mono">
                {r.rank}
                {finalIds.has(r.chunk_id) && <span className="sr-only"> (sent)</span>}
              </td>
              <td className="px-2 py-1">
                {location(r)}
                {finalIds.has(r.chunk_id) && <span className="ml-1"><Badge tone="accent">in top K</Badge></span>}
              </td>
              {columns.map((c) => (
                <td key={c.label} className="px-2 py-1 font-mono whitespace-nowrap">{c.value(r)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Step({ n, title, hint, children }: { n: number; title: string; hint: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h4 className="text-sm font-semibold">
        {n}. {title}
      </h4>
      <p className="text-xs text-zinc-600 dark:text-zinc-400">{hint}</p>
      {children}
    </section>
  );
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className="text-xs font-medium text-orange-800 underline dark:text-orange-300"
      onClick={() => {
        navigator.clipboard?.writeText(text).then(
          () => setDone(true),
          () => setDone(false),
        );
      }}
    >
      {done ? "Copied" : label}
    </button>
  );
}

/** "How this answer was made": every step from the question to the model output (§6.3). */
export default function PipelineView({ pipeline, finalIds }: { pipeline: Pipeline; finalIds: Set<string> }) {
  const p = pipeline;
  return (
    <details className="rounded-md border border-zinc-200 dark:border-zinc-800">
      <summary className="cursor-pointer p-3 text-sm font-medium">How this answer was made</summary>
      <div className="space-y-5 border-t border-zinc-200 p-3 dark:border-zinc-800">
        <Step n={1} title="Question" hint="The text as the server received it.">
          <p className="rounded bg-zinc-50 p-2 text-sm dark:bg-zinc-900">{p.question}</p>
        </Step>
        <Step n={2} title="Query rewrite" hint="Rewriting the question before searching (an optional step).">
          <p className="text-sm">Not used.</p>
        </Step>
        <Step n={3} title="Query embedding" hint="The question becomes a vector of numbers that captures its meaning.">
          {p.query_embedding ? (
            <p className="text-sm">
              {p.query_embedding.model} · {p.query_embedding.dims} dimensions · {formatMs(p.query_embedding.ms)}
              {p.query_embedding.cached && <> · <Badge tone="good">cached</Badge></>}
            </p>
          ) : (
            <p className="text-sm">Not available.</p>
          )}
        </Step>
        <Step n={4} title="Vector search (ChromaDB)" hint="Chunks whose meaning is closest to the question. Similarity: higher is closer.">
          <CandidateTable
            rows={p.vector_candidates}
            label="Vector search candidates"
            finalIds={finalIds}
            columns={[{ label: "Similarity", value: (c) => num(c.similarity) }]}
          />
        </Step>
        <Step n={5} title="Keyword search (BM25)" hint="Chunks that contain the question's words. Matched terms show why each one matched.">
          <CandidateTable
            rows={p.bm25_candidates}
            label="Keyword search candidates"
            finalIds={finalIds}
            columns={[
              { label: "Score", value: (c) => num(c.score, 2) },
              {
                label: "Matched terms",
                value: (c) => (Array.isArray(c.matched_terms) ? (c.matched_terms as string[]).join(", ") : "—"),
              },
            ]}
          />
        </Step>
        <Step n={6} title="Fusion (weighted RRF)" hint="Both lists merged by rank: 0.7 for vectors, 0.3 for keywords. The top K are kept.">
          <CandidateTable
            rows={p.rrf_merged}
            label="Fused ranking"
            finalIds={finalIds}
            columns={[
              { label: "RRF", value: (c) => num(c.rrf, 4) },
              { label: "Vector rank", value: (c) => rank(c.vector) },
              { label: "BM25 rank", value: (c) => rank(c.bm25) },
            ]}
          />
        </Step>
        <Step n={7} title="Rerank" hint="A cross-encoder reads the question with each chunk and reorders them.">
          {p.reranked ? (
            <CandidateTable
              rows={p.reranked}
              label="Reranked results"
              finalIds={finalIds}
              columns={[
                { label: "Score", value: (c) => num(c.rerank, 2) },
                { label: "Move", value: (c) => `${rank(c.rank_before)} → ${c.rank}` },
              ]}
            />
          ) : (
            <p className="text-sm">{SKIP_REASONS[p.rerank_skipped ?? ""] ?? `Not run (${p.rerank_skipped}).`}</p>
          )}
        </Step>
        {p.prompt && (
          <Step n={8} title="Prompt" hint="The exact text sent to Gemini: instructions, then the question and the numbered excerpts.">
            <p className="text-xs">
              prompt v{p.prompt.prompt_version} · about {p.prompt.est_tokens} tokens · {p.prompt.chunks_sent} excerpts sent
              {p.prompt.chunks_dropped > 0 && ` · ${p.prompt.chunks_dropped} dropped (context budget)`}
            </p>
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium">System</span>
              <CopyButton text={p.prompt.system} label="Copy system prompt" />
            </div>
            <CodeBlock code={p.prompt.system} label="System prompt" maxHeight="max-h-48" lineNumbers={false} />
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium">User</span>
              <CopyButton text={p.prompt.user} label="Copy user prompt" />
            </div>
            <CodeBlock code={p.prompt.user} label="User prompt" maxHeight="max-h-64" lineNumbers={false} />
          </Step>
        )}
        {p.llm && (
          <Step n={9} title="Model output" hint="Gemini's raw JSON reply, before it is checked and shown.">
            <p className="text-xs">
              {p.llm.cached ? "From the cache (0 AI calls)" : "Real call"} · tokens {p.llm.input_tokens ?? "—"} in /{" "}
              {p.llm.output_tokens ?? "—"} out
            </p>
            {p.llm.attempts.length > 1 ? (
              p.llm.attempts.map((a, i) => (
                <div key={i} className="space-y-1">
                  <p className="text-xs font-medium">Attempt {i + 1}</p>
                  {a.repair_message && <p className="text-xs">Repair request: {a.repair_message}</p>}
                  {a.raw_output && <CodeBlock code={a.raw_output} label={`Model output, attempt ${i + 1}`} maxHeight="max-h-48" lineNumbers={false} />}
                  {a.errors.length > 0 && (
                    <ul className="list-disc pl-5 text-xs text-red-800 dark:text-red-300">
                      {a.errors.map((e) => <li key={e}>{e}</li>)}
                    </ul>
                  )}
                </div>
              ))
            ) : (
              p.llm.raw_output && <CodeBlock code={p.llm.raw_output} label="Model output" maxHeight="max-h-48" lineNumbers={false} />
            )}
          </Step>
        )}
      </div>
    </details>
  );
}
