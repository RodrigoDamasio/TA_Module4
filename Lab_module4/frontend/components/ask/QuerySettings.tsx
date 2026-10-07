"use client";
import Badge from "@/components/Badge";
import { MODE_HINTS, modeLabel } from "@/lib/format";
import type { Codebase, Config, SearchMode } from "@/lib/schemas";

interface Props {
  config: Config;
  codebases: Codebase[];
  selected: string[];
  mode: SearchMode;
  k: number;
  open: boolean;
  onToggle: (open: boolean) => void;
  onSelected: (ids: string[]) => void;
  onMode: (mode: SearchMode) => void;
  onK: (k: number) => void;
}

export default function QuerySettings(p: Props) {
  const modes = p.config.modes;
  const current = modes.find((m) => m.id === p.mode);
  const unavailable = modes.filter((m) => !m.available);
  const summary = `${p.selected.length ? p.selected.join(", ") : "no codebase"} · ${modeLabel(p.mode)} · K ${p.k}`;

  function toggle(id: string) {
    p.onSelected(p.selected.includes(id) ? p.selected.filter((s) => s !== id) : [...p.selected, id]);
  }

  return (
    <details
      open={p.open}
      onToggle={(e) => p.onToggle((e.currentTarget as HTMLDetailsElement).open)}
      className="rounded-md border border-zinc-200 dark:border-zinc-800"
    >
      <summary className="cursor-pointer p-3 text-sm">
        <span className="font-medium">Settings:</span> {summary}
      </summary>
      <div className="grid grid-cols-1 gap-4 border-t border-zinc-200 p-3 sm:grid-cols-[2fr_1fr_auto] dark:border-zinc-800">
        <fieldset className="space-y-1">
          <legend className="text-sm font-medium">Codebases</legend>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {p.codebases.map((c) => (
              <label key={c.id} className="flex items-center gap-1.5 text-sm">
                <input type="checkbox" checked={p.selected.includes(c.id)} onChange={() => toggle(c.id)} />
                {c.id}
                <Badge>{c.kind === "sample" ? "sample" : "uploaded"}</Badge>
              </label>
            ))}
          </div>
          <button
            type="button"
            onClick={() => p.onSelected(p.codebases.map((c) => c.id))}
            className="text-xs font-medium text-orange-800 underline dark:text-orange-300"
          >
            Select all
          </button>
        </fieldset>
        <div className="space-y-1">
          <label htmlFor="mode" className="block text-sm font-medium">
            Search mode
          </label>
          <select
            id="mode"
            value={p.mode}
            onChange={(e) => p.onMode(e.target.value as SearchMode)}
            className="w-full rounded border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            aria-describedby="mode-hint"
          >
            {modes.map((m) => (
              <option key={m.id} value={m.id} disabled={!m.available}>
                {modeLabel(m.id)}
                {m.available ? "" : " (unavailable)"}
              </option>
            ))}
          </select>
          <p id="mode-hint" className="text-xs text-zinc-600 dark:text-zinc-400">
            {MODE_HINTS[p.mode]}
            {current && !current.available && ` ${current.reason}`}
          </p>
          {unavailable.map((m) => (
            <p key={m.id} className="text-xs text-zinc-600 dark:text-zinc-400">
              {modeLabel(m.id)} is unavailable: {m.reason}
            </p>
          ))}
        </div>
        <div className="space-y-1">
          <label htmlFor="k" className="block text-sm font-medium">
            Excerpts (K)
          </label>
          <select
            id="k"
            value={p.k}
            onChange={(e) => p.onK(Number(e.target.value))}
            className="rounded border border-zinc-300 bg-white px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
          >
            {Array.from({ length: p.config.limits.max_k }, (_, i) => i + 1).map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </div>
      </div>
    </details>
  );
}
