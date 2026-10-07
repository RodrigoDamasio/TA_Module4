import Badge from "@/components/Badge";
import CodeBlock from "@/components/CodeBlock";
import { lineRange } from "@/lib/format";
import type { Source } from "@/lib/schemas";

const fmt = (v: number | null, digits: number) => (v === null ? "—" : v.toFixed(digits));

export default function SourceCard({
  source,
  domId,
  cited,
  flash,
}: {
  source: Source;
  domId: string;
  cited: boolean;
  flash: boolean;
}) {
  const s = source;
  const where = `${s.path}:${lineRange(s.start_line, s.end_line)}`;
  const ranks = Object.entries(s.scores.ranks);
  return (
    <details
      id={domId}
      tabIndex={-1}
      open={cited}
      className={`rounded-md border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950 ${flash ? "flash" : ""}`}
    >
      <summary className="cursor-pointer list-none space-y-1 p-3 [&::-webkit-details-marker]:hidden">
        <span className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm font-semibold">[{s.n}]</span>
          <Badge>{s.codebase}</Badge>
          {cited && <Badge tone="accent">cited</Badge>}
          {s.part && <Badge title="This unit was split in parts">part {s.part[0]}/{s.part[1]}</Badge>}
        </span>
        <span className="block font-mono text-xs break-all text-zinc-800 dark:text-zinc-200">{where}</span>
        {s.symbol && <span className="block text-xs text-zinc-600 dark:text-zinc-400">{s.symbol}</span>}
        <span className="block text-xs text-zinc-600 dark:text-zinc-400">
          vector {fmt(s.scores.vector, 2)} · BM25 {fmt(s.scores.bm25, 2)} · RRF {fmt(s.scores.rrf, 3)}
          {s.scores.rerank !== null && <> · rerank {fmt(s.scores.rerank, 2)}</>}
          {" · ranks: "}
          {ranks.length ? ranks.map(([name, r]) => `${name === "bm25" ? "BM25" : name} ${r}`).join(", ") : "—"}
        </span>
      </summary>
      <div className="px-3 pb-3">
        <CodeBlock code={s.code} startLine={s.start_line} label={`Code of source ${s.n}, ${where}`} />
      </div>
    </details>
  );
}
