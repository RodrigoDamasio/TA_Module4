/** Files from a drag and drop, including whole folders (FileSystemEntry API). */
import type { Candidate } from "./upload";

interface Entry {
  isFile: boolean;
  isDirectory: boolean;
  name: string;
  file?: (ok: (f: File) => void, fail: (e: unknown) => void) => void;
  createReader?: () => { readEntries: (ok: (entries: Entry[]) => void, fail: (e: unknown) => void) => void };
}

async function walk(entry: Entry, prefix: string, out: Candidate[]): Promise<void> {
  if (entry.isFile && entry.file) {
    const file = await new Promise<File>((ok, fail) => entry.file!(ok, fail));
    out.push({ path: prefix + entry.name, size: file.size, read: () => file.text() });
    return;
  }
  if (entry.isDirectory && entry.createReader) {
    const reader = entry.createReader();
    // readEntries returns at most ~100 entries per call: read until it returns none.
    for (;;) {
      const batch = await new Promise<Entry[]>((ok, fail) => reader.readEntries(ok, fail));
      if (batch.length === 0) break;
      for (const child of batch) await walk(child, `${prefix}${entry.name}/`, out);
    }
  }
}

/** Candidates from a drop. A single dropped folder's own name is dropped from the paths and
 * returned as the suggested codebase name. */
export async function fromDrop(data: DataTransfer): Promise<{ candidates: Candidate[]; folder: string | null }> {
  const entries: Entry[] = [];
  for (const item of Array.from(data.items ?? [])) {
    const entry = (item.webkitGetAsEntry?.() ?? null) as Entry | null;
    if (entry) entries.push(entry);
  }
  if (entries.length === 0) {
    const files = Array.from(data.files ?? []);
    return { candidates: files.map((f) => ({ path: f.name, size: f.size, read: () => f.text() })), folder: null };
  }
  const out: Candidate[] = [];
  for (const e of entries) await walk(e, "", out);
  if (entries.length === 1 && entries[0].isDirectory) {
    const root = `${entries[0].name}/`;
    return {
      candidates: out.map((c) => ({ ...c, path: c.path.startsWith(root) ? c.path.slice(root.length) : c.path })),
      folder: entries[0].name,
    };
  }
  return { candidates: out, folder: null };
}
