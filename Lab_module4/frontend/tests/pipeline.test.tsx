import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import PipelineView from "@/components/ask/PipelineView";
import { fx } from "./fixtures";

const base = fx.queryDebug.pipeline!;

describe("PipelineView", () => {
  it("shows each repair attempt with its errors", async () => {
    const pipeline = {
      ...base,
      prompt: { ...base.prompt!, chunks_dropped: 2 },
      llm: {
        ...base.llm!,
        cached: true,
        attempts: [
          { raw_output: '{"answer": "x [7]"}', errors: ["[7] does not exist"], repair_message: null },
          { raw_output: '{"answer": "x [1]"}', errors: [], repair_message: "Fix the citations." },
        ],
      },
      reranked: [{ ...base.rrf_merged[0], rank: 1, rerank: 4.2, rank_before: 3 }],
    };
    const user = userEvent.setup();
    render(<PipelineView pipeline={pipeline} finalIds={new Set()} />);
    await user.click(screen.getByText("How this answer was made"));
    expect(screen.getByText("Attempt 2")).toBeInTheDocument();
    expect(screen.getByText("[7] does not exist")).toBeInTheDocument();
    expect(screen.getByText("Repair request: Fix the citations.")).toBeInTheDocument();
    expect(screen.getByText(/2 dropped \(context budget\)/)).toBeInTheDocument();
    expect(screen.getByText(/From the cache/)).toBeInTheDocument();
    expect(screen.getByText("3 → 1")).toBeInTheDocument();

    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    await user.click(screen.getByRole("button", { name: "Copy user prompt" }));
    expect(writeText).toHaveBeenCalledWith(base.prompt!.user);
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("explains a missing embedding and other skip reasons", async () => {
    const user = userEvent.setup();
    render(<PipelineView pipeline={{ ...base, query_embedding: null, rerank_skipped: "loading", bm25_candidates: [] }} finalIds={new Set()} />);
    await user.click(screen.getByText("How this answer was made"));
    expect(screen.getByText("Not available.")).toBeInTheDocument();
    expect(screen.getByText(/still loading/)).toBeInTheDocument();
    expect(screen.getByText("No candidates.")).toBeInTheDocument();
  });
});
