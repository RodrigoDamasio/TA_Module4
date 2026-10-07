/** Upload rules (FRONTEND_PLAN §5): the same skip rules as the backend's domain/files.py, with
 * the values from GET /config, so nothing is sent that the server would refuse. Files are
 * classified by path first and read only when they can be indexed (node_modules is never read). */
import type { Config } from "./schemas";

export type Rules = Pick<Config, "limits" | "files">;

export const SKIP_LABELS = {
  dependency: "dependency or build folder",
  secrets: "secrets file (.env)",
  lockfile: "lockfile",
  unsupported: "unsupported file type",
  binary: "binary file",
  minified: "minified or generated (very long lines)",
  path_too_long: "path too long",
  duplicate: "duplicate path",
  too_large: "file too large for one request",
  unreadable: "could not be read",
} as const;
export type SkipReason = keyof typeof SKIP_LABELS;

export interface UploadEntry {
  path: string;
  content: string;
  bytes: number;
}

export interface Skipped {
  path: string;
  reason: SkipReason;
}

export interface Review {
  accepted: UploadEntry[];
  skipped: Skipped[]; // dependency folders are only counted, see `dependencyFiles`
  dependencyFiles: number;
  totalBytes: number;
  problems: string[]; // codebase limits exceeded: indexing is blocked
}

const encoder = new TextEncoder();
export const utf8Bytes = (text: string): number => encoder.encode(text).length;

/** Path inside the project: a folder pick drops the folder's own name ("proj/app/x.py" → "app/x.py"). */
export function relativePath(file: File): string {
  const rel = (file as File & { webkitRelativePath?: string }).webkitRelativePath;
  if (rel && rel.includes("/")) return rel.split("/").slice(1).join("/");
  return file.name;
}

function extension(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot).toLowerCase() : "";
}

/** Reasons that need only the path (and size), so the file is never read. */
export function pathSkipReason(path: string, size: number, rules: Rules): SkipReason | null {
  const parts = path.split("/");
  const name = parts[parts.length - 1];
  if (parts.slice(0, -1).some((p) => rules.files.skipped_dirs.includes(p))) return "dependency";
  if (name === ".env" || (name.startsWith(".env.") && !rules.files.extra_names.includes(name))) {
    return "secrets";
  }
  if (rules.files.lockfiles.includes(name)) return "lockfile";
  if (!rules.files.extra_names.includes(name) && !rules.files.extensions.includes(extension(name))) {
    return "unsupported";
  }
  if (path.length > rules.limits.max_path_chars) return "path_too_long";
  if (size > rules.limits.max_bytes_per_request) return "too_large";
  return null;
}

/** Reasons that need the content. */
export function contentSkipReason(content: string, rules: Rules): SkipReason | null {
  if (content.includes("\u0000")) return "binary";
  const limit = rules.limits.minified_line_chars;
  if (content.split(/\r?\n/).some((line) => line.length > limit)) return "minified";
  return null;
}

export interface Candidate {
  path: string;
  size: number;
  read: () => Promise<string>;
}

export function fromFiles(files: File[]): Candidate[] {
  return files.map((f) => ({ path: relativePath(f), size: f.size, read: () => f.text() }));
}

/** Classifies every candidate, reads the indexable ones, and checks the codebase limits. */
export async function review(candidates: Candidate[], rules: Rules): Promise<Review> {
  const accepted: UploadEntry[] = [];
  const skipped: Skipped[] = [];
  const seen = new Set<string>();
  let dependencyFiles = 0;
  const sorted = [...candidates].sort((a, b) => a.path.localeCompare(b.path));
  for (const c of sorted) {
    const byPath = pathSkipReason(c.path, c.size, rules);
    if (byPath === "dependency") {
      dependencyFiles += 1;
      continue;
    }
    if (byPath) {
      skipped.push({ path: c.path, reason: byPath });
      continue;
    }
    if (seen.has(c.path)) {
      skipped.push({ path: c.path, reason: "duplicate" });
      continue;
    }
    let content: string;
    try {
      content = await c.read();
    } catch {
      skipped.push({ path: c.path, reason: "unreadable" });
      continue;
    }
    const byContent = contentSkipReason(content, rules);
    if (byContent) {
      skipped.push({ path: c.path, reason: byContent });
      continue;
    }
    seen.add(c.path);
    accepted.push({ path: c.path, content, bytes: utf8Bytes(content) });
  }
  const totalBytes = accepted.reduce((sum, f) => sum + f.bytes, 0);
  const problems = limitProblems(accepted, totalBytes, rules);
  return { accepted, skipped, dependencyFiles, totalBytes, problems };
}

export function limitProblems(accepted: UploadEntry[], totalBytes: number, rules: Rules): string[] {
  const { max_files_per_codebase: maxFiles, max_bytes_per_codebase: maxBytes } = rules.limits;
  const problems: string[] = [];
  if (accepted.length > maxFiles) {
    problems.push(`Too many files: ${accepted.length} of ${maxFiles}. Remove some files.`);
  }
  if (totalBytes > maxBytes) {
    problems.push(
      `Too much code: ${formatKb(totalBytes)} of ${formatKb(maxBytes)}. Remove some files.`,
    );
  }
  return problems;
}

function formatKb(bytes: number): string {
  if (bytes >= 1_000_000) return `${(bytes / 1_000_000).toFixed(1)} MB`;
  return `${Math.ceil(bytes / 1000)} KB`;
}

/** Splits the files into requests in path order: a new batch when the next file would pass
 * the per-request file count or byte limit. */
export function batches(files: UploadEntry[], rules: Rules): UploadEntry[][] {
  const { max_files_per_request: maxFiles, max_bytes_per_request: maxBytes } = rules.limits;
  const out: UploadEntry[][] = [];
  let current: UploadEntry[] = [];
  let bytes = 0;
  for (const file of files) {
    if (current.length > 0 && (current.length >= maxFiles || bytes + file.bytes > maxBytes)) {
      out.push(current);
      current = [];
      bytes = 0;
    }
    current.push(file);
    bytes += file.bytes;
  }
  if (current.length > 0) out.push(current);
  return out;
}
