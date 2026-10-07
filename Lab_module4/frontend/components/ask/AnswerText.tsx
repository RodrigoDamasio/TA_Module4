import { splitAnswer } from "@/lib/citations";
import { lineRange } from "@/lib/format";
import type { Source } from "@/lib/schemas";

/** The answer as text (never HTML), with each [n] citation as a button to its source. */
export default function AnswerText({
  text,
  sources,
  onCite,
}: {
  text: string;
  sources: Source[];
  onCite: (n: number) => void;
}) {
  const byN = new Map(sources.map((s) => [s.n, s]));
  return (
    <p className="leading-7 whitespace-pre-wrap">
      {splitAnswer(text).map((seg, i) => {
        if (seg.type === "text") return <span key={i}>{seg.text}</span>;
        if (seg.type === "code") {
          return (
            <code key={i} className="rounded bg-zinc-100 px-1 font-mono text-[0.9em] dark:bg-zinc-800">
              {seg.text}
            </code>
          );
        }
        return (
          <span key={i} className="whitespace-nowrap">
            {seg.numbers.map((n) => {
              const s = byN.get(n);
              if (!s) return <span key={n}>[{n}]</span>;
              return (
                <button
                  key={n}
                  type="button"
                  onClick={() => onCite(n)}
                  aria-label={`Source ${n}: ${s.path} lines ${lineRange(s.start_line, s.end_line)}`}
                  className="mx-0.5 rounded bg-orange-50 px-1 font-mono text-xs font-semibold text-orange-800 underline-offset-2 hover:underline dark:bg-orange-950 dark:text-orange-200"
                >
                  [{n}]
                </button>
              );
            })}
          </span>
        );
      })}
    </p>
  );
}
