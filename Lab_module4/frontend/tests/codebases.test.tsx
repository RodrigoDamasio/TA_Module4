import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CodebasesApp from "@/components/codebases/CodebasesApp";
import CodebaseView from "@/components/codebases/CodebaseView";
import * as api from "@/lib/api";
import { ApiError } from "@/lib/api";
import type { Codebase, Job } from "@/lib/schemas";
import { fx } from "./fixtures";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    config: vi.fn(),
    listCodebases: vi.fn(),
    deleteCodebase: vi.fn(),
    indexFiles: vi.fn(),
    getJob: vi.fn(),
    getCodebase: vi.fn(),
    listChunks: vi.fn(),
  };
});

const m = vi.mocked(api);
const userCodebase: Codebase = {
  ...fx.codebases[0],
  id: "auction-checklist",
  kind: "user",
  read_only: false,
  chunk_count: 48,
  expires_at: new Date(Date.now() + 23 * 3600_000).toISOString(),
};

function folderFile(path: string, content: string): File {
  const file = new File([content], path.split("/").pop() ?? path);
  Object.defineProperty(file, "webkitRelativePath", { value: path });
  return file;
}

function pick(input: HTMLElement, files: File[]) {
  fireEvent.change(input, { target: { files } }); // the app does its own filtering (no `accept`)
}

beforeEach(() => {
  m.config.mockResolvedValue(fx.config);
  m.listCodebases.mockResolvedValue([...fx.codebases, userCodebase]);
  m.indexFiles.mockResolvedValue({ ...fx.jobIndex, status: "queued" } as Job);
  m.getJob.mockResolvedValue(fx.jobIndex);
  m.deleteCodebase.mockResolvedValue(undefined);
});

describe("Codebases page", () => {
  // C12
  it("lists samples first, read-only, and uploads with expiry and delete", async () => {
    const user = userEvent.setup();
    render(<CodebasesApp />);
    const items = await screen.findAllByRole("listitem");
    expect(within(items[0]).getByText("sample · read-only")).toBeInTheDocument();
    expect(within(items[0]).queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    const mine = items[2];
    expect(await within(mine).findByText(/expires in 23 h/)).toBeInTheDocument();
    expect(screen.getByText(/1 of 10 upload slots used/)).toBeInTheDocument();
    await user.click(within(mine).getByRole("button", { name: "Delete" }));
    expect(within(mine).getByText("Delete auction-checklist and its 48 chunks?")).toBeInTheDocument();
    await user.click(within(mine).getByRole("button", { name: "Confirm delete" }));
    expect(m.deleteCodebase).toHaveBeenCalledWith("auction-checklist");
    await waitFor(() => expect(m.listCodebases).toHaveBeenCalledTimes(2));
  });

  it("shows a delete failure", async () => {
    m.deleteCodebase.mockRejectedValue(new ApiError("not_found", "This codebase no longer exists."));
    const user = userEvent.setup();
    render(<CodebasesApp />);
    const items = await screen.findAllByRole("listitem");
    await user.click(within(items[2]).getByRole("button", { name: "Delete" }));
    await user.click(within(items[2]).getByRole("button", { name: "Confirm delete" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("no longer exists");
  });

  // C10
  it("reviews a picked folder: paths, skips, totals, suggested name", async () => {
    const user = userEvent.setup();
    render(<CodebasesApp />);
    const folder = await screen.findByTestId("folder-input");
    pick(folder, [
      folderFile("Auction_Checklist/auction/checks.py", "def check(): pass\n"),
      folderFile("Auction_Checklist/README.md", "# Auction\n"),
      folderFile("Auction_Checklist/node_modules/x/index.js", "x"),
      folderFile("Auction_Checklist/package-lock.json", "{}"),
      folderFile("Auction_Checklist/.env", "KEY=1"),
    ]);
    expect(await screen.findByText(/2 files accepted, 2 skipped \(\+1 in dependency or build folders\)/)).toBeInTheDocument();
    expect(screen.getByLabelText("Codebase name")).toHaveValue("auction-checklist");
    const table = screen.getByRole("region", { name: "Files to index" });
    expect(within(table).getByText("auction/checks.py")).toBeInTheDocument();
    await user.click(screen.getByText("Skipped files (2)"));
    expect(screen.getByText(/: lockfile/)).toBeInTheDocument();
    expect(screen.getByText(/: secrets file/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Index" })).toBeEnabled();

    await user.clear(screen.getByLabelText("Codebase name"));
    await user.type(screen.getByLabelText("Codebase name"), "shopflow");
    expect(screen.getByRole("button", { name: "Index" })).toBeDisabled();
    expect(screen.getAllByText(/read-only sample/).length).toBeGreaterThan(0);
    await user.clear(screen.getByLabelText("Codebase name"));
    await user.type(screen.getByLabelText("Codebase name"), "auction-checklist");
    expect(screen.getByText(/exists: it will be re-indexed/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.queryByRole("region", { name: "Files to index" })).not.toBeInTheDocument();
  });

  it("blocks codebases over the limits", async () => {
    m.config.mockResolvedValue({ ...fx.config, limits: { ...fx.config.limits, max_files_per_codebase: 1 } });
    render(<CodebasesApp />);
    pick(await screen.findByTestId("files-input"), [new File(["a"], "a.py"), new File(["b"], "b.py")]);
    expect(await screen.findByText("Too many files: 2 of 1. Remove some files.", { selector: "p.text-red-800" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Index" })).toBeDisabled();
  });

  // C11
  it("indexes in batches and reports the result", async () => {
    m.config.mockResolvedValue({ ...fx.config, limits: { ...fx.config.limits, max_files_per_request: 1 } });
    const user = userEvent.setup();
    render(<CodebasesApp />);
    pick(await screen.findByTestId("files-input"), [new File(["x = 1"], "a.py"), new File(["y = 2"], "b.py")]);
    await screen.findByText(/sent in 2 requests/);
    await user.type(screen.getByLabelText("Codebase name"), "demo");
    await user.click(screen.getByRole("button", { name: "Index" }));
    expect(await screen.findByText(/demo: 2 files indexed/, {}, { timeout: 5000 })).toBeInTheDocument();
    expect(m.indexFiles.mock.calls.map((c) => c[1][0].path)).toEqual(["a.py", "b.py"]);
    expect(screen.getByText(/Skipped by the server: package-lock.json \(lockfile\)/)).toBeInTheDocument();
    const links = screen.getAllByRole("link", { name: "Ask about it" }).map((a) => a.getAttribute("href"));
    expect(links).toContain("/?cb=demo");
    expect(screen.getByRole("link", { name: "See its files and chunks" })).toHaveAttribute("href", "/codebases/demo");
  });

  it("shows a failed batch and retries from it", async () => {
    m.config.mockResolvedValue({ ...fx.config, limits: { ...fx.config.limits, max_files_per_request: 1 } });
    m.indexFiles
      .mockResolvedValueOnce(fx.jobIndex)
      .mockRejectedValueOnce(new ApiError("full", "The demo holds at most 3 uploaded codebases."))
      .mockResolvedValueOnce(fx.jobIndex);
    const user = userEvent.setup();
    render(<CodebasesApp />);
    pick(await screen.findByTestId("files-input"), [new File(["x"], "a.py"), new File(["y"], "b.py")]);
    await screen.findByText(/sent in 2 requests/);
    await user.type(screen.getByLabelText("Codebase name"), "demo");
    await user.click(screen.getByRole("button", { name: "Index" }));
    expect(await screen.findByText("Request 2 of 2 failed: The demo holds at most 3 uploaded codebases.")).toBeInTheDocument();
    expect(screen.getByText("The files of the earlier requests are indexed.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry from request 2" }));
    expect(await screen.findByText(/demo: 2 files indexed/)).toBeInTheDocument();
    expect(m.indexFiles).toHaveBeenCalledTimes(3);
  });
});

describe("Codebase detail", () => {
  it("lists files and shows how a file was split", async () => {
    m.getCodebase.mockResolvedValue(fx.codebaseDetail);
    m.listChunks.mockResolvedValue(fx.chunks);
    const user = userEvent.setup();
    render(<CodebaseView id="shopflow" />);
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("shopflow");
    expect(screen.getByRole("link", { name: "Ask about this codebase" })).toHaveAttribute("href", "/?cb=shopflow");
    await user.click(screen.getByRole("button", { name: "backend/app/db.py" }));
    expect(m.listChunks).toHaveBeenCalledWith("shopflow", "backend/app/db.py");
    expect(await screen.findByText(`${fx.chunks.length} chunk${fx.chunks.length === 1 ? "" : "s"}`, { exact: false })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Chunk 1 of backend/app/db.py" })).toBeInTheDocument();
  });

  it("explains a missing codebase", async () => {
    m.getCodebase.mockRejectedValue(new ApiError("not_found", "This codebase no longer exists. Uploaded codebases expire after 24 hours."));
    render(<CodebaseView id="gone" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("expire after 24 hours");
    expect(screen.getByRole("link", { name: "Back to codebases" })).toBeInTheDocument();
  });
});
