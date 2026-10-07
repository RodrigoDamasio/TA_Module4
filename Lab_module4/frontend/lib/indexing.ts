/** Sends upload batches one after the other to the same codebase, following each index job
 * until it ends (FRONTEND_PLAN §4). `sleep` and `api` are injectable for tests. */
import * as defaultApi from "./api";
import { ApiError } from "./api";
import {
  type IndexProgress,
  IndexProgressSchema,
  type IndexResult,
  IndexResultSchema,
  type Job,
} from "./schemas";
import type { UploadEntry } from "./upload";

export interface BatchUpdate {
  batch: number; // 0-based
  batches: number;
  progress: IndexProgress | null;
}

export interface Totals {
  files_indexed: number;
  files_unchanged: number;
  chunks_added: number;
  chunks_removed: number;
  embedding_cache_hits: number;
  skipped: { path: string; reason: string }[];
}

export class BatchFailed extends Error {
  constructor(
    public batch: number,
    message: string,
    public totals: Totals,
  ) {
    super(message);
    this.name = "BatchFailed";
  }
}

type Api = Pick<typeof defaultApi, "indexFiles" | "getJob">;

const wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export const emptyTotals = (): Totals => ({
  files_indexed: 0,
  files_unchanged: 0,
  chunks_added: 0,
  chunks_removed: 0,
  embedding_cache_hits: 0,
  skipped: [],
});

export function addResult(totals: Totals, r: IndexResult): Totals {
  return {
    files_indexed: totals.files_indexed + r.files_indexed,
    files_unchanged: totals.files_unchanged + r.files_unchanged,
    chunks_added: totals.chunks_added + r.chunks_added,
    chunks_removed: totals.chunks_removed + r.chunks_removed,
    embedding_cache_hits: totals.embedding_cache_hits + r.embedding_cache_hits,
    skipped: [...totals.skipped, ...r.skipped],
  };
}

/** Polls a job until it is completed or failed. */
export async function followJob(
  job: Job,
  onProgress: (job: Job) => void,
  { api = defaultApi as Api, sleep = wait, intervalMs = 1000 } = {},
): Promise<Job> {
  let current = job;
  onProgress(current);
  while (current.status === "queued" || current.status === "running") {
    await sleep(intervalMs);
    current = await api.getJob(current.id);
    onProgress(current);
  }
  return current;
}

export async function indexAll(
  codebase: string,
  batches: UploadEntry[][],
  onUpdate: (u: BatchUpdate) => void,
  { api = defaultApi as Api, sleep = wait, start = 0, totals = emptyTotals() } = {},
): Promise<Totals> {
  let sum = totals;
  for (let i = start; i < batches.length; i++) {
    onUpdate({ batch: i, batches: batches.length, progress: null });
    let job: Job;
    try {
      const files = batches[i].map(({ path, content }) => ({ path, content }));
      job = await api.indexFiles(codebase, files);
      job = await followJob(
        job,
        (j) => {
          const progress = IndexProgressSchema.safeParse(j.progress);
          onUpdate({ batch: i, batches: batches.length, progress: progress.success ? progress.data : null });
        },
        { api, sleep },
      );
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "The upload failed.";
      throw new BatchFailed(i, message, sum);
    }
    if (job.status === "failed") {
      throw new BatchFailed(i, job.error?.detail ?? "The index job failed.", sum);
    }
    const result = IndexResultSchema.safeParse(job.result);
    if (!result.success) throw new BatchFailed(i, "Unexpected response from the server.", sum);
    sum = addResult(sum, result.data);
  }
  return sum;
}
