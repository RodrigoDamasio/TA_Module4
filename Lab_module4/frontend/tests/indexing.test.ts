import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { BatchFailed, followJob, indexAll } from "@/lib/indexing";
import type { Job } from "@/lib/schemas";
import { fx } from "./fixtures";

const done = fx.jobIndex;
const running: Job = { ...done, status: "running", result: null, progress: { files_done: 1, files_total: 2, chunks: 1, cache_hits: 0 } };
const failed: Job = { ...done, status: "failed", result: null, error: { title: "ModelsLoading", detail: "models loading" } };
const sleep = () => Promise.resolve();
const batch = (n: number) => [{ path: `f${n}.py`, content: "x", bytes: 1 }];

describe("indexAll", () => {
  it("sends the batches in order, polls each job and adds up the results", async () => {
    const api = {
      indexFiles: vi.fn().mockResolvedValue(running),
      getJob: vi.fn().mockResolvedValueOnce(running).mockResolvedValueOnce(done).mockResolvedValueOnce(done),
    };
    const updates: unknown[] = [];
    const totals = await indexAll("demo", [batch(1), batch(2)], (u) => updates.push(u), { api, sleep });
    expect(api.indexFiles.mock.calls.map((c) => c[1][0].path)).toEqual(["f1.py", "f2.py"]);
    expect(api.indexFiles.mock.calls[0][1][0]).toEqual({ path: "f1.py", content: "x" }); // no byte counts sent
    expect(totals.files_indexed).toBe(2);
    expect(totals.skipped).toHaveLength(2);
    expect(updates).toContainEqual({ batch: 0, batches: 2, progress: { files_done: 1, files_total: 2, chunks: 1, cache_hits: 0 } });
  });

  it("stops at a failed job and can resume from it", async () => {
    const api = { indexFiles: vi.fn().mockResolvedValueOnce(done).mockResolvedValueOnce(failed), getJob: vi.fn() };
    const err = await indexAll("demo", [batch(1), batch(2)], () => {}, { api, sleep }).catch((e) => e);
    expect(err).toBeInstanceOf(BatchFailed);
    expect(err.batch).toBe(1);
    expect(err.message).toBe("models loading");
    expect(err.totals.files_indexed).toBe(1);
    api.indexFiles.mockResolvedValueOnce(done);
    const totals = await indexAll("demo", [batch(1), batch(2)], () => {}, { api, sleep, start: 1, totals: err.totals });
    expect(totals.files_indexed).toBe(2);
  });

  it("turns API errors and bad results into BatchFailed", async () => {
    const api = { indexFiles: vi.fn().mockRejectedValue(new ApiError("full", "No more slots.")), getJob: vi.fn() };
    const err = await indexAll("demo", [batch(1)], () => {}, { api, sleep }).catch((e) => e);
    expect(err.message).toBe("No more slots.");
    api.indexFiles.mockRejectedValue(new Error("boom"));
    expect((await indexAll("demo", [batch(1)], () => {}, { api, sleep }).catch((e) => e)).message).toBe("The upload failed.");
    api.indexFiles.mockResolvedValue({ ...done, result: { nope: 1 } });
    expect((await indexAll("demo", [batch(1)], () => {}, { api, sleep }).catch((e) => e)).message).toMatch(/Unexpected/);
  });

  it("followJob polls until the job ends", async () => {
    const api = { indexFiles: vi.fn(), getJob: vi.fn().mockResolvedValueOnce(running).mockResolvedValueOnce(done) };
    const seen: string[] = [];
    const end = await followJob({ ...running, status: "queued" }, (j) => seen.push(j.status), { api, sleep });
    expect(end.status).toBe("completed");
    expect(seen).toEqual(["queued", "running", "completed"]);
  });
});
