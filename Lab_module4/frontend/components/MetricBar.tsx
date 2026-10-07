/** A metric as a number plus a plain bar (0..max). The number carries the meaning. */
export default function MetricBar({
  label,
  value,
  max = 1,
  display,
  compact = false,
}: {
  label: string;
  value: number | null;
  max?: number;
  display: string;
  compact?: boolean; // in a table whose column header already names the metric
}) {
  const width = value === null ? 0 : Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className={compact ? "sr-only" : "w-28 shrink-0 text-zinc-700 dark:text-zinc-300"}>{label}</span>
      <span className="h-2 flex-1 rounded bg-zinc-200 dark:bg-zinc-800" aria-hidden="true">
        <span className="block h-2 rounded bg-orange-600" style={{ width: `${width}%` }} />
      </span>
      <span className="w-12 text-right font-mono tabular-nums">{display}</span>
    </div>
  );
}
