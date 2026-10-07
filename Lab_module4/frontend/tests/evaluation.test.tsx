import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EvaluationApp from "@/components/evaluation/EvaluationApp";
import HealthDot from "@/components/HealthDot";
import Nav from "@/components/Nav";
import * as api from "@/lib/api";
import { ApiError } from "@/lib/api";
import type { Job } from "@/lib/schemas";
import { DATASET_TEMPLATE } from "@/lib/template";
import { fx } from "./fixtures";

vi.mock("next/navigation", () => ({ usePathname: () => "/evaluation" }));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    config: vi.fn(),
    health: vi.fn(),
    getReport: vi.fn(),
    getGrid: vi.fn(),
    runRetrieval: vi.fn(),
    runFull: vi.fn(),
    getJob: vi.fn(),
    stats: vi.fn(),
  };
});

const m = vi.mocked(api);

beforeEach(() => {
  m.config.mockResolvedValue(fx.config);
  m.getReport.mockResolvedValue(fx.reportFull);
  m.getGrid.mockResolvedValue(fx.grid);
  m.runRetrieval.mockResolvedValue(fx.reportRetrieval);
  m.runFull.mockResolvedValue({ ...fx.jobEvaluate, status: "running", result: null } as Job);
  m.getJob.mockResolvedValue(fx.jobEvaluate);
  m.stats.mockResolvedValue(fx.stats);
  m.health.mockResolvedValue({ status: "ok", models: "ready", reranker: "disabled", samples: "current" });
});

describe("Evaluation page", () => {
  // C13
  it("shows the stored full report with categories, checks and per-question details", async () => {
    const user = userEvent.setup();
    render(<EvaluationApp />);
    expect(await screen.findByText("0.815")).toBeInTheDocument();
    expect(screen.getByText("4.72 / 5")).toBeInTheDocument();
    expect(screen.getByText(/Citations valid: 20 \/ 20/)).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Metrics by category" })).getByText("Cross-codebase")).toBeInTheDocument();
    expect(screen.getByText(/wrong function described/)).toBeInTheDocument();
    await user.click(screen.getByText("What does the processOrder function do?"));
    expect(screen.getAllByText("relevant").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Judge's reasons").length).toBeGreaterThan(0);
    expect(m.getReport).toHaveBeenCalledWith("full");
  });

  it("filters and sorts the comparison grid; tabs work with the keyboard", async () => {
    const user = userEvent.setup();
    render(<EvaluationApp />);
    await user.click(screen.getByRole("tab", { name: "Comparison grid" }));
    expect(await screen.findByText("24 of 72 rows")).toBeInTheDocument(); // K 5 by default
    expect(screen.getAllByText("server default")).toHaveLength(1);
    await user.selectOptions(screen.getByLabelText("Chunking"), "fixed");
    await user.selectOptions(screen.getByLabelText("Mode"), "vector");
    expect(screen.getByText("2 of 72 rows")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("K"), "");
    await user.selectOptions(screen.getByLabelText("Sort by"), "context_chars");
    expect(screen.getByText("6 of 72 rows")).toBeInTheDocument();

    screen.getByRole("tab", { name: "Comparison grid" }).focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Run" })).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{End}");
    expect(screen.getByRole("tab", { name: "Server" })).toHaveFocus();
    expect(await screen.findByText("Real AI calls today")).toBeInTheDocument();
    await user.keyboard("{Home}{ArrowLeft}");
    expect(screen.getByRole("tab", { name: "Server" })).toHaveAttribute("aria-selected", "true");
  });

  it("runs a retrieval evaluation and replays the full one", async () => {
    const user = userEvent.setup();
    render(<EvaluationApp />);
    await user.click(screen.getByRole("tab", { name: "Run" }));
    await user.selectOptions(await screen.findByLabelText("K"), "3");
    await user.selectOptions(screen.getByLabelText("Search mode"), "bm25");
    await user.click(screen.getByRole("button", { name: "Run retrieval evaluation" }));
    expect(m.runRetrieval).toHaveBeenCalledWith({ k: 3, search_mode: "bm25" });
    expect(await screen.findByText(/Retrieval evaluation · 20 questions/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Replay full evaluation" }));
    expect(await screen.findByText(/Full evaluation · 20 questions/, {}, { timeout: 3000 })).toBeInTheDocument();
    expect(m.getJob).toHaveBeenCalled();
  });

  it("shows run errors", async () => {
    m.runRetrieval.mockRejectedValue(new ApiError("rate_limited", "Too many requests in a short time.", 20));
    const user = userEvent.setup();
    render(<EvaluationApp />);
    await user.click(screen.getByRole("tab", { name: "Run" }));
    await user.click(await screen.findByRole("button", { name: "Run retrieval evaluation" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many requests");
    expect(screen.getByRole("button", { name: "Run retrieval evaluation" })).toBeDisabled();
  });

  // C14
  it("validates and runs a custom dataset", async () => {
    m.runRetrieval.mockRejectedValueOnce(new ApiError("validation", "Invalid examples", undefined, ["Examples: unknown symbol"]));
    const user = userEvent.setup();
    render(<EvaluationApp />);
    await user.click(screen.getByRole("tab", { name: "Run" }));
    await user.click(await screen.findByText("Your own dataset (retrieval only)"));
    const box = screen.getByLabelText("Custom dataset JSON");
    await user.type(box, "[[");
    await user.click(screen.getByRole("button", { name: "Run on my dataset" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Not valid JSON");
    await user.clear(box);
    await user.click(screen.getByRole("button", { name: "Paste the template" }));
    await user.click(screen.getByRole("button", { name: "Run on my dataset" }));
    expect(await screen.findByText("Examples: unknown symbol")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Run on my dataset" }));
    expect(m.runRetrieval).toHaveBeenLastCalledWith({ k: 5, search_mode: "hybrid", examples: DATASET_TEMPLATE });
    expect(await screen.findByText(/Retrieval evaluation/)).toBeInTheDocument();
    const createObjectURL = vi.fn(() => "blob:x");
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() }));
    await user.click(screen.getByRole("button", { name: "Download a template" }));
    expect(createObjectURL).toHaveBeenCalled();
  });

  it("shows a load error with retry", async () => {
    m.getReport.mockRejectedValueOnce(new ApiError("network", "Can't reach the service."));
    const user = userEvent.setup();
    render(<EvaluationApp />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Can't reach");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("0.815")).toBeInTheDocument();
  });
});

describe("Navigation", () => {
  it("marks the current page and shows the server state in words", async () => {
    render(<Nav />);
    expect(screen.getByRole("link", { name: "Evaluation" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Ask" })).not.toHaveAttribute("aria-current");
    expect(await screen.findByText("Server ready · reranker disabled")).toBeInTheDocument();
  });

  it("says when the server is unreachable or loading", async () => {
    m.health.mockRejectedValueOnce(new ApiError("network", "x"));
    const { unmount } = render(<HealthDot />);
    expect(await screen.findByText("Server unreachable")).toBeInTheDocument();
    unmount();
    m.health.mockResolvedValueOnce({ status: "ok", models: "loading", reranker: "ready", samples: "pending" });
    render(<HealthDot />);
    expect(await screen.findByText("Models loading")).toBeInTheDocument();
  });
});
