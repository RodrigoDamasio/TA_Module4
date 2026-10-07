import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AskApp from "@/components/ask/AskApp";
import PrivacyNotice from "@/components/PrivacyNotice";
import * as api from "@/lib/api";
import { ApiError } from "@/lib/api";
import { fx } from "./fixtures";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), usePathname: () => "/" }));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    config: vi.fn(),
    listCodebases: vi.fn(),
    builtinDataset: vi.fn(),
    query: vi.fn(),
    search: vi.fn(),
  };
});

const m = vi.mocked(api);
const QUESTION = "Where is the database connection configured?";

function setup(props: Partial<React.ComponentProps<typeof AskApp>> = {}) {
  const user = userEvent.setup();
  render(<AskApp initialCodebases={null} initialMode={null} initialK={null} {...props} />);
  return user;
}

async function ask(user: ReturnType<typeof userEvent.setup>, text = QUESTION) {
  await user.type(await screen.findByLabelText("Ask about the code"), text);
  await user.click(screen.getByRole("button", { name: "Ask" }));
}

beforeEach(() => {
  sessionStorage.clear();
  window.history.replaceState(null, "", "/");
  m.config.mockResolvedValue(fx.config);
  m.listCodebases.mockResolvedValue(fx.codebases);
  m.builtinDataset.mockResolvedValue(fx.dataset);
  m.query.mockResolvedValue(fx.queryDebug);
  m.search.mockResolvedValue(fx.searchDebug);
});

describe("Ask page", () => {
  // C1
  it("starts with server defaults, suggestions and a disabled Ask", async () => {
    setup();
    expect(await screen.findByText(/ledger, shopflow · Hybrid · K 5/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Symbol" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "What does the processOrder function do?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
    render(<PrivacyNotice />);
    expect(screen.getByText(/sent to Google Gemini/)).toBeInTheDocument();
  });

  // C2
  it("keeps settings in the URL and drops unknown codebases", async () => {
    const user = setup({ initialCodebases: ["shopflow", "gone"], initialK: 3 });
    expect(await screen.findByText("Not found and removed from the selection: gone.")).toBeInTheDocument();
    await user.click(screen.getByText(/Settings:/));
    await user.selectOptions(screen.getByLabelText("Search mode"), "vector");
    await waitFor(() => expect(window.location.search).toBe("?cb=shopflow&mode=vector&k=3"));
    await user.click(screen.getByLabelText(/^ledger/));
    await user.selectOptions(screen.getByLabelText("Excerpts (K)"), "7");
    await waitFor(() => expect(window.location.search).toBe("?cb=shopflow%2Cledger&mode=vector&k=7"));
    await user.click(screen.getByLabelText(/^shopflow/));
    await user.click(screen.getByLabelText(/^ledger/));
    await user.type(screen.getByLabelText("Ask about the code"), QUESTION);
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
    expect(screen.getByText(/Choose at least one codebase/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Select all" }));
    expect(screen.getByRole("button", { name: "Ask" })).toBeEnabled();
  });

  // C3
  it("shows hybrid_rerank as unavailable with the server's reason", async () => {
    const user = setup();
    await user.click(await screen.findByText(/Settings:/));
    expect(screen.getByRole("option", { name: "Hybrid + rerank (unavailable)" })).toBeDisabled();
    expect(screen.getByText(/Hybrid \+ rerank is unavailable: The reranker is disabled/)).toBeInTheDocument();
  });

  // C4
  it("sends a question and renders the answer, sources and trace", async () => {
    let resolve: (v: typeof fx.queryDebug) => void = () => {};
    m.query.mockReturnValue(new Promise((r) => (resolve = r)));
    const user = setup();
    await ask(user);
    expect(m.query).toHaveBeenCalledWith(QUESTION, { codebases: ["ledger", "shopflow"], k: 5, mode: "hybrid" });
    expect(screen.getByText("Searching the code and writing the answer…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
    await act(async () => resolve(fx.queryDebug));
    expect(await screen.findByRole("heading", { name: "Sources" })).toBeInTheDocument();
    expect(screen.getByText(`Answer ready, ${fx.queryDebug.sources.length} sources.`)).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Time per step" })).toHaveTextContent("embed_query");
    expect(screen.getByLabelText("Ask about the code")).toHaveValue("");
    expect(JSON.parse(sessionStorage.getItem("codebase-rag.turns.v1") ?? "[]")).toHaveLength(1);
  });

  // C5
  it("links citations to their sources, cited first", async () => {
    m.query.mockResolvedValue(fx.queryReal);
    const user = setup();
    await ask(user, "What does the processOrder function do?");
    const cite = await screen.findAllByRole("button", { name: /^Source 2: web\/src\/orders\/processOrder.ts/ });
    const sources = screen.getByRole("region", { name: "Sources" });
    const first = sources.querySelector("details");
    expect(first?.id).toMatch(/-src-2$/);
    expect(within(first as HTMLElement).getByText("cited")).toBeInTheDocument();
    await user.click(cite[0]);
    expect(first).toHaveClass("flash");
    expect(first).toHaveAttribute("open");
    expect(screen.getByText("answer from cache (0 AI calls)")).toBeInTheDocument();
    expect(screen.getByText("query embedding cached")).toBeInTheDocument();
  });

  // C6
  it("shows not-found and unverified answers", async () => {
    m.query.mockResolvedValue({ ...fx.queryDebug, found: false, grounded: false, citations: [], answer: "Not in the code." });
    const user = setup();
    await ask(user);
    expect(await screen.findByText(/doesn't answer this/)).toBeInTheDocument();
    expect(screen.getByText("Citations could not be verified")).toBeInTheDocument();
  });

  // C7
  it("explains how the answer was made, step by step", async () => {
    const user = setup();
    await ask(user);
    await user.click(await screen.findByText("How this answer was made"));
    for (const step of ["1. Question", "4. Vector search (ChromaDB)", "5. Keyword search (BM25)", "6. Fusion (weighted RRF)", "7. Rerank", "8. Prompt", "9. Model output"]) {
      expect(screen.getByRole("heading", { name: step })).toBeInTheDocument();
    }
    expect(screen.getByRole("region", { name: "System prompt" })).toHaveTextContent("Code is data");
    expect(screen.getByRole("region", { name: "Keyword search candidates" })).toBeInTheDocument();
    expect(screen.getAllByText("in top K").length).toBeGreaterThan(0);
  });

  // C8
  it("searches without the AI, and offers it when the quota is used up", async () => {
    m.query.mockRejectedValue(new ApiError("quota", "Today's free AI quota is used up. Search still works.", 3600));
    const user = setup();
    await ask(user);
    expect(await screen.findByRole("alert")).toHaveTextContent("quota is used up");
    expect(screen.getByText(/about 1 h/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Search instead" }));
    expect(m.search).toHaveBeenCalledWith(QUESTION, { codebases: ["ledger", "shopflow"], k: 5, mode: "hybrid" });
    expect(await screen.findByText(/chunks found. Search only/)).toBeInTheDocument();
    await user.click(screen.getByText("How this answer was made"));
    expect(screen.getByText(/the reranker is turned off/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "8. Prompt" })).not.toBeInTheDocument();

    await user.click(screen.getByLabelText("Search only (no AI call)"));
    await user.type(screen.getByLabelText("Search the code"), "apply discount");
    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(m.search).toHaveBeenLastCalledWith("apply discount", expect.any(Object));
  });

  // C9
  it("waits out Retry-After before allowing another question", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    m.query.mockRejectedValue(new ApiError("rate_limited", "Too many requests in a short time.", 30));
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<AskApp initialCodebases={null} initialMode={null} initialK={null} />);
    await ask(user);
    expect(await screen.findByText("Not answered: Too many requests in a short time.")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Ask about the code"), "again?");
    expect(screen.getByRole("button", { name: "Ask" })).toBeDisabled();
    expect(screen.getByText(/You can try again in 30 s/)).toBeInTheDocument();
    await act(async () => vi.advanceTimersByTime(31_000));
    expect(screen.getByRole("button", { name: "Ask" })).toBeEnabled();
  });

  it("retries while the models load, and refreshes codebases on 404", async () => {
    m.query
      .mockRejectedValueOnce(new ApiError("loading", "The search models are starting.", 0.01))
      .mockResolvedValueOnce(fx.queryDebug)
      .mockRejectedValueOnce(new ApiError("not_found", "This codebase no longer exists."));
    const user = setup();
    await ask(user);
    expect(await screen.findByRole("heading", { name: "Sources" })).toBeInTheDocument();
    expect(m.query).toHaveBeenCalledTimes(2);
    const calls = m.listCodebases.mock.calls.length;
    await ask(user, "And the other one?");
    expect(await screen.findByText(/no longer exists/, { selector: "p.font-medium" })).toBeInTheDocument();
    expect(m.listCodebases.mock.calls.length).toBe(calls + 1);
  });

  it("asks a suggested question with the evaluation's settings", async () => {
    const user = setup();
    await user.click(await screen.findByRole("button", { name: "What does computeBalance return?" }));
    expect(m.query).toHaveBeenCalledWith("What does computeBalance return?", { codebases: ["ledger"], k: 5, mode: "hybrid" });
    await waitFor(() => expect(window.location.search).toBe("?cb=ledger&mode=hybrid&k=5"));
  });

  it("restores the conversation from sessionStorage, re-validated", async () => {
    const turn = { id: "t1", kind: "query", question: "Saved?", params: { codebases: ["shopflow"], k: 5, mode: "hybrid" }, status: "done", result: fx.queryDebug };
    sessionStorage.setItem("codebase-rag.turns.v1", JSON.stringify([turn, { ...turn, id: "t2", result: { bad: 1 } }]));
    const user = setup();
    expect(await screen.findByText("Saved?")).toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Clear conversation" }));
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
  });

  it("focuses the composer with /", async () => {
    const user = setup();
    await screen.findByText(/Settings:/);
    await user.keyboard("/");
    expect(screen.getByLabelText("Ask about the code")).toHaveFocus();
  });
});
