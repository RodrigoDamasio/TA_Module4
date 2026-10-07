/** Display formatting for numbers, sizes, durations and dates. */

export function formatMs(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)} s`;
  if (ms >= 10) return `${Math.round(ms)} ms`;
  return `${ms.toFixed(1)} ms`;
}

export function formatBytes(bytes: number): string {
  if (bytes >= 1_000_000) return `${(bytes / 1_000_000).toFixed(1)} MB`;
  if (bytes >= 1000) return `${(bytes / 1000).toFixed(1)} KB`;
  return `${bytes} B`;
}

/** 0.8148 → "0.815"; null → "—". */
export function metric(value: number | null | undefined, digits = 3): string {
  return value === null || value === undefined ? "—" : value.toFixed(digits);
}

export function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${Math.round(value * 100)} %`;
}

export function lineRange(start: number, end: number): string {
  return start === end ? `${start}` : `${start}–${end}`;
}

/** Seconds → "45 s", "2 min 5 s", "about 5 h". */
export function formatDuration(seconds: number): string {
  if (seconds >= 3600) return `about ${Math.round(seconds / 3600)} h`;
  if (seconds >= 60) return `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
  return `${seconds} s`;
}

/** "expires in 23 h" / "expires in 40 min" / "expired". */
export function expiresIn(iso: string, now: number): string {
  const left = Date.parse(iso) - now;
  if (Number.isNaN(left)) return "";
  if (left <= 0) return "expired";
  const minutes = Math.round(left / 60_000);
  return minutes >= 90 ? `expires in ${Math.round(minutes / 60)} h` : `expires in ${minutes} min`;
}

export function formatDate(iso: string): string {
  const date = new Date(iso.includes("T") || iso.includes(" ") ? iso.replace(" ", "T") : iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toISOString().slice(0, 16).replace("T", " ") + " UTC";
}

const CATEGORY_LABELS: Record<string, string> = {
  symbol: "Symbol",
  conceptual: "Conceptual",
  location: "Location",
  multi_file: "Multi-file",
  cross_codebase: "Cross-codebase",
  unanswerable: "Unanswerable",
};

export function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category;
}

const MODE_LABELS: Record<string, string> = {
  hybrid: "Hybrid",
  vector: "Vector",
  bm25: "BM25 (keywords)",
  hybrid_rerank: "Hybrid + rerank",
};

export function modeLabel(mode: string): string {
  return MODE_LABELS[mode] ?? mode;
}

export const MODE_HINTS: Record<string, string> = {
  hybrid: "Meaning and exact words together. Best overall in the evaluation.",
  vector: "Meaning only. Good for questions in plain language.",
  bm25: "Exact words only. Good for names like processOrder.",
  hybrid_rerank: "Hybrid, then a cross-encoder reorders the top 20.",
};
