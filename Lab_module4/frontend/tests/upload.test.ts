import { describe, expect, it, vi } from "vitest";
import { batches, type Candidate, contentSkipReason, fromFiles, limitProblems, pathSkipReason, relativePath, review, utf8Bytes } from "@/lib/upload";
import { fx } from "./fixtures";

const rules = fx.config;
const cand = (path: string, content = "x = 1\n", size = content.length): Candidate & { read: ReturnType<typeof vi.fn> } => ({
  path,
  size,
  read: vi.fn().mockResolvedValue(content),
});

describe("path rules mirror the backend", () => {
  it.each([
    ["node_modules/x/index.js", "dependency"],
    ["web/.next/a.js", "dependency"],
    [".env", "secrets"],
    ["config/.env.production", "secrets"],
    ["package-lock.json", "lockfile"],
    ["logo.png", "unsupported"],
    ["Makefile", "unsupported"],
    [`${"a/".repeat(100)}x.py`, "path_too_long"],
  ])("%s → %s", (path, reason) => {
    expect(pathSkipReason(path, 10, rules)).toBe(reason);
  });

  it("accepts code, docs, config and .env.example", () => {
    for (const p of ["app/main.py", "src/App.TSX", "README.md", "pyproject.toml", ".env.example"]) {
      expect(pathSkipReason(p, 10, rules)).toBeNull();
    }
    expect(pathSkipReason("big.py", rules.limits.max_bytes_per_request + 1, rules)).toBe("too_large");
  });

  it("detects binary and minified content", () => {
    expect(contentSkipReason("a\u0000b", rules)).toBe("binary");
    expect(contentSkipReason("x".repeat(rules.limits.minified_line_chars + 1), rules)).toBe("minified");
    expect(contentSkipReason("ok\nfine", rules)).toBeNull();
  });
});

describe("review", () => {
  it("reads only indexable files, counts dependency folders, reports skips", async () => {
    const dep = cand("node_modules/lib/index.js");
    const png = cand("logo.png");
    const files = [cand("b.py", "é"), cand("a.py"), dep, png, cand("min.js", "y".repeat(2000))];
    const r = await review(files, rules);
    expect(r.accepted.map((f) => f.path)).toEqual(["a.py", "b.py"]);
    expect(r.accepted[1].bytes).toBe(2); // UTF-8 bytes, like the server
    expect(r.dependencyFiles).toBe(1);
    expect(r.skipped).toEqual([
      { path: "logo.png", reason: "unsupported" },
      { path: "min.js", reason: "minified" },
    ]);
    expect(dep.read).not.toHaveBeenCalled();
    expect(png.read).not.toHaveBeenCalled();
    expect(r.problems).toEqual([]);
    expect(r.totalBytes).toBe(utf8Bytes("x = 1\n") + 2);
  });

  it("skips duplicates and unreadable files", async () => {
    const broken: Candidate = { path: "c.py", size: 1, read: () => Promise.reject(new Error("io")) };
    const r = await review([cand("a.py"), cand("a.py"), broken], rules);
    expect(r.skipped).toEqual([
      { path: "a.py", reason: "duplicate" },
      { path: "c.py", reason: "unreadable" },
    ]);
  });

  it("explains codebase limits", () => {
    const many = Array.from({ length: rules.limits.max_files_per_codebase + 1 }, (_, i) => ({ path: `${i}.py`, content: "", bytes: 1 }));
    expect(limitProblems(many, 2_000_000, rules)).toEqual([
      `Too many files: ${many.length} of ${rules.limits.max_files_per_codebase}. Remove some files.`,
      "Too much code: 2.0 MB of 1.0 MB. Remove some files.",
    ]);
    expect(limitProblems([], 1500, { ...rules, limits: { ...rules.limits, max_bytes_per_codebase: 1000 } })[0]).toContain("2 KB of 1 KB");
  });
});

describe("batches", () => {
  const entry = (path: string, bytes: number) => ({ path, content: "", bytes });
  it("splits on file count and bytes, in order", () => {
    const small = { ...rules, limits: { ...rules.limits, max_files_per_request: 2, max_bytes_per_request: 100 } };
    const out = batches([entry("a", 10), entry("b", 10), entry("c", 10), entry("d", 95), entry("e", 5)], small);
    expect(out.map((b) => b.map((f) => f.path))).toEqual([["a", "b"], ["c"], ["d", "e"]]);
    expect(batches([], small)).toEqual([]);
  });
});

describe("file paths", () => {
  it("drops the picked folder's own name", () => {
    const file = new File(["x"], "main.py");
    Object.defineProperty(file, "webkitRelativePath", { value: "project/app/main.py" });
    expect(relativePath(file)).toBe("app/main.py");
    expect(relativePath(new File(["x"], "solo.py"))).toBe("solo.py");
    expect(fromFiles([file])[0]).toMatchObject({ path: "app/main.py", size: 1 });
  });
});
