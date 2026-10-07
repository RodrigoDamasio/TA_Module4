import { categoryLabel } from "@/lib/format";
import type { Example } from "@/lib/schemas";

/** The built-in evaluation questions: their answers are cached on the server, so they're free. */
export default function Suggestions({
  examples,
  disabled,
  onPick,
}: {
  examples: Example[];
  disabled: boolean;
  onPick: (example: Example) => void;
}) {
  const groups = new Map<string, Example[]>();
  for (const e of examples) groups.set(e.category, [...(groups.get(e.category) ?? []), e]);
  return (
    <section aria-labelledby="suggestions" className="space-y-3">
      <div>
        <h2 id="suggestions" className="text-lg font-semibold">
          Try a question
        </h2>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          About the two sample codebases. These were asked before, so the answers come from the cache.
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {[...groups.entries()].map(([category, items]) => (
          <div key={category} className="space-y-1">
            <h3 className="text-xs font-semibold tracking-wide text-zinc-600 uppercase dark:text-zinc-400">
              {categoryLabel(category)}
            </h3>
            <ul className="space-y-1">
              {items.map((e) => (
                <li key={e.id}>
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => onPick(e)}
                    className="text-left text-sm text-orange-800 underline-offset-2 hover:underline disabled:text-zinc-500 dark:text-orange-300"
                  >
                    {e.question}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
