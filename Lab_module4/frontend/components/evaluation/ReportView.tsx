import Badge from "@/components/Badge";
import MetricBar from "@/components/MetricBar";
import { categoryLabel, formatDate, formatMs, metric } from "@/lib/format";
import type { Report } from "@/lib/schemas";
import QuestionTable from "./QuestionTable";

const CHECK_LABELS: Record<string, string> = {
  citations_valid: "Citations valid",
  found_matches: "found matches the expectation",
  mentions_ok: "Required terms mentioned",
  no_forbidden: "No forbidden content (planted injection)",
};

function Card({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-md border border-zinc-200 p-3 dark:border-zinc-800">
      <p className="text-xs text-zinc-600 dark:text-zinc-400">{label}</p>
      <p className="text-xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="text-xs text-zinc-600 dark:text-zinc-400">{hint}</p>}
    </div>
  );
}

export default function ReportView({ report }: { report: Report }) {
  const s = report.summary;
  const r = s.retrieval.overall;
  const g = s.generation?.overall;
  const k = typeof report.config.k === "number" ? report.config.k : 5;
  const mode = typeof report.config.mode === "string" ? report.config.mode : "";
  const categories = Object.keys(s.retrieval.by_category);
  return (
    <div className="space-y-6">
      <p className="text-sm text-zinc-600 dark:text-zinc-400">
        {report.kind === "full" ? "Full evaluation" : "Retrieval evaluation"} · {s.n_examples} questions · K {k} · {mode} ·{" "}
        {String(report.config.embedder ?? "")} · {formatDate(report.created_at)}
        {s.calls && ` · ${s.calls.real_calls} real AI calls, ${s.calls.cached_calls} from cache`}
      </p>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Card label={`Recall@${k}`} value={metric(r.recall)} hint="Share of the right code found" />
        <Card label="MRR" value={metric(r.mrr)} hint="How high the first right chunk ranks" />
        <Card label={`nDCG@${k}`} value={metric(r.ndcg)} hint="Ranking quality, 0 to 1" />
        <Card label={`Precision@${k}`} value={metric(r.precision)} hint="Share of retrieved chunks that are right" />
        {g && (
          <>
            <Card label="Faithfulness" value={`${metric(g.faithfulness, 2)} / 5`} hint="Claims supported by the excerpts" />
            <Card label="Relevance" value={`${metric(g.relevance, 2)} / 5`} hint="Answers the question asked" />
            <Card label="Correctness" value={`${metric(g.correctness, 2)} / 5`} hint="Matches the reference answer" />
          </>
        )}
        {s.judge_sanity && (
          <Card label="Judge sanity check" value={`${s.judge_sanity.passed} / ${s.judge_sanity.total}`} hint="Planted bad answers scored ≤ 2" />
        )}
        {s.latency_ms && <Card label="Retrieval latency p50" value={`${formatMs(s.latency_ms.p50 ?? 0)}`} hint={`p95 ${formatMs(s.latency_ms.p95 ?? 0)}`} />}
      </div>

      {s.checks && (
        <section aria-labelledby="checks-title" className="space-y-2">
          <h3 id="checks-title" className="font-semibold">Deterministic checks</h3>
          <ul className="space-y-1 text-sm">
            {Object.entries(s.checks).map(([name, c]) => (
              <li key={name} className="flex items-center gap-2">
                <Badge tone={c.passed === c.total ? "good" : "warn"}>{c.passed === c.total ? "pass" : "partial"}</Badge>
                {CHECK_LABELS[name] ?? name}: {c.passed} / {c.total}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-labelledby="cat-title" className="space-y-2">
        <h3 id="cat-title" className="font-semibold">By category</h3>
        <div role="region" aria-label="Metrics by category" tabIndex={0} className="overflow-x-auto">
          <table className="w-full min-w-[32rem] text-left text-sm">
            <caption className="sr-only">Metrics by question category</caption>
            <thead className="text-xs text-zinc-600 dark:text-zinc-400">
              <tr>
                <th scope="col" className="py-1 pr-2">Category</th>
                <th scope="col" className="py-1 pr-2">Questions</th>
                <th scope="col" className="py-1 pr-2">Recall</th>
                <th scope="col" className="py-1 pr-2">MRR</th>
                {s.generation && <th scope="col" className="py-1 pr-2">Correctness</th>}
              </tr>
            </thead>
            <tbody>
              {categories.map((c) => {
                const m = s.retrieval.by_category[c];
                const j = s.generation?.by_category[c];
                return (
                  <tr key={c} className="border-t border-zinc-200 dark:border-zinc-800">
                    <th scope="row" className="py-1 pr-2 font-normal">{categoryLabel(c)}</th>
                    <td className="py-1 pr-2 tabular-nums">{m.n ?? "—"}</td>
                    <td className="py-1 pr-2"><MetricBar label="Recall" value={m.recall} display={metric(m.recall, 2)} compact /></td>
                    <td className="py-1 pr-2"><MetricBar label="MRR" value={m.mrr} display={metric(m.mrr, 2)} compact /></td>
                    {s.generation && (
                      <td className="py-1 pr-2">
                        <MetricBar label="Correctness" value={j?.correctness ?? null} max={5} display={metric(j?.correctness, 2)} compact />
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-zinc-600 dark:text-zinc-400">
          Unanswerable questions have no right code, so they have no retrieval score; they pass when the answer says
          the code doesn&apos;t contain it.
        </p>
      </section>

      {report.judge_sanity && report.judge_sanity.length > 0 && (
        <section aria-labelledby="sanity-title" className="space-y-2">
          <h3 id="sanity-title" className="font-semibold">Judge sanity check</h3>
          <p className="text-xs text-zinc-600 dark:text-zinc-400">
            Deliberately bad answers given to the judge. A trustworthy judge scores them low.
          </p>
          <ul className="space-y-1 text-sm">
            {report.judge_sanity.map((j) => (
              <li key={j.id} className="flex flex-wrap items-center gap-2">
                <Badge tone={j.passed ? "good" : "bad"}>{j.passed ? "rejected" : "missed"}</Badge>
                {j.kind}: faithfulness {j.scores.faithfulness ?? "—"}, relevance {j.scores.relevance ?? "—"}, correctness{" "}
                {j.scores.correctness ?? "—"}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-labelledby="questions-title" className="space-y-2">
        <h3 id="questions-title" className="font-semibold">Per question</h3>
        <QuestionTable examples={report.examples} />
      </section>

      <details className="text-sm">
        <summary className="cursor-pointer font-medium">How to read this</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-zinc-700 dark:text-zinc-300">
          <li>Recall@K: of the code that answers the question, how much was in the top K chunks sent to the model.</li>
          <li>MRR: 1 when the first right chunk is ranked first, 0.5 when second, and so on.</li>
          <li>Judge scores (1–5) come from the same model that answers, so treat them as an upper bound. The sanity check shows the judge does reject bad answers.</li>
          <li>With 18 scored questions, one question moves recall or MRR by about 0.05: smaller differences are noise.</li>
        </ul>
      </details>
    </div>
  );
}
