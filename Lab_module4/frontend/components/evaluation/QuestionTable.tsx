import Badge from "@/components/Badge";
import { categoryLabel, lineRange, metric } from "@/lib/format";
import type { ReportExample } from "@/lib/schemas";

function Detail({ e }: { e: ReportExample }) {
  return (
    <div className="space-y-3 p-3 text-sm">
      <div>
        <p className="font-medium">Retrieved</p>
        <ol className="space-y-0.5 text-xs">
          {e.retrieved.map((r) => (
            <li key={r.rank} className="flex flex-wrap items-center gap-2">
              <span className="font-mono">{r.rank}.</span>
              <Badge tone={r.relevant ? "good" : "neutral"}>{r.relevant ? "relevant" : "not relevant"}</Badge>
              <span className="font-mono break-all">
                {r.codebase}/{r.path}:{lineRange(r.lines[0], r.lines[1])}
              </span>
              {r.symbol && <span className="text-zinc-600 dark:text-zinc-400">{r.symbol}</span>}
            </li>
          ))}
        </ol>
      </div>
      {e.answer && (
        <div>
          <p className="font-medium">
            Answer {e.answer.found ? "" : <Badge>found: false</Badge>} {e.answer.cached && <Badge tone="good">cached</Badge>}
          </p>
          <p className="whitespace-pre-wrap">{e.answer.text}</p>
        </div>
      )}
      {e.judge_reasons && (
        <div>
          <p className="font-medium">Judge&apos;s reasons</p>
          <ul className="list-disc pl-5">
            {Object.entries(e.judge_reasons).map(([k, v]) => (
              <li key={k}>
                <span className="font-medium">{k}</span> ({e.judge_scores?.[k as "faithfulness"] ?? "—"}): {v}
              </li>
            ))}
          </ul>
        </div>
      )}
      {e.missing_mentions && e.missing_mentions.length > 0 && (
        <p>Required terms not mentioned: {e.missing_mentions.map((m) => `"${m}"`).join(", ")}</p>
      )}
    </div>
  );
}

export default function QuestionTable({ examples }: { examples: ReportExample[] }) {
  const judged = examples.some((e) => e.judge_scores);
  return (
    <ul className="divide-y divide-zinc-200 rounded-md border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
      {examples.map((e) => {
        const failed = e.checks ? Object.entries(e.checks).filter(([, ok]) => !ok).map(([n]) => n) : [];
        return (
          <li key={e.id}>
            <details>
              <summary className="cursor-pointer space-y-1 p-3">
                <span className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-mono text-xs">{e.id}</span>
                  <Badge>{categoryLabel(e.category)}</Badge>
                  <span className="font-medium">{e.question}</span>
                </span>
                <span className="block text-xs text-zinc-600 dark:text-zinc-400">
                  {e.metrics ? `R ${metric(e.metrics.recall, 2)} · MRR ${metric(e.metrics.mrr, 2)}` : "no retrieval score"}
                  {judged && e.judge_scores && ` · judge ${e.judge_scores.faithfulness}/${e.judge_scores.relevance}/${e.judge_scores.correctness}`}
                  {e.checks && (failed.length === 0 ? " · all checks pass" : ` · failed: ${failed.join(", ")}`)}
                </span>
              </summary>
              <Detail e={e} />
            </details>
          </li>
        );
      })}
    </ul>
  );
}
