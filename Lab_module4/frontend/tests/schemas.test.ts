import { describe, expect, it } from "vitest";
import { IndexResultSchema, ReportListItemSchema, ReportSchema } from "@/lib/schemas";
import { fx, raw } from "./fixtures";

describe("schemas parse every recorded API response", () => {
  it("parses all fixtures", () => {
    expect(fx.config.modes.find((m) => m.id === "hybrid_rerank")?.available).toBe(false);
    expect(fx.queryReal.trace.cache?.llm).toBe(true);
    expect(fx.queryReal.answer).toContain("[2]");
    expect(fx.searchDebug.pipeline?.rerank_skipped).toBe("disabled");
    expect(fx.reportFull.examples).toHaveLength(20);
    expect(fx.grid.rows).toHaveLength(72);
    expect(IndexResultSchema.parse(fx.jobIndex.result).skipped[0].reason).toBe("lockfile");
    expect(ReportSchema.parse(fx.jobEvaluate.result).kind).toBe("full");
    expect(ReportListItemSchema.array().parse(raw.evaluations).length).toBeGreaterThan(0);
    expect(fx.reportRetrieval.kind).toBe("retrieval");
  });

  it("rejects a response with a wrong type", () => {
    const bad = { ...raw.queryDebug, citations: "1" };
    expect(() => ReportSchema.parse(bad)).toThrow();
  });
});
