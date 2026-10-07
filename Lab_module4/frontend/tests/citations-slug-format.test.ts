import { describe, expect, it } from "vitest";
import { citedNumbers, splitAnswer } from "@/lib/citations";
import {
  categoryLabel, expiresIn, formatBytes, formatDate, formatDuration, formatMs, lineRange, metric, modeLabel, percent,
} from "@/lib/format";
import { nameError, suggestName } from "@/lib/slug";

describe("citations", () => {
  it("splits single and grouped markers and inline code", () => {
    expect(splitAnswer("Uses `jwt` [1] and [2, 3].")).toEqual([
      { type: "text", text: "Uses " },
      { type: "code", text: "jwt" },
      { type: "text", text: " " },
      { type: "cite", numbers: [1] },
      { type: "text", text: " and " },
      { type: "cite", numbers: [2, 3] },
      { type: "text", text: "." },
    ]);
    expect(splitAnswer("a list [x] is text")).toEqual([{ type: "text", text: "a list [x] is text" }]);
    expect(citedNumbers("[2] then [1,2] and [3]")).toEqual([2, 1, 3]);
  });
});

describe("codebase names", () => {
  const pattern = "^[a-z0-9][a-z0-9-]{0,39}$";
  it("suggests a valid name from a folder", () => {
    expect(suggestName("Auction_Checklist")).toBe("auction-checklist");
    expect(suggestName("  São José Leilões!! ")).toBe("sao-jose-leiloes");
    expect(suggestName("x".repeat(60))).toHaveLength(40);
  });
  it("explains invalid names", () => {
    expect(nameError("", pattern, [])).toMatch(/name/);
    expect(nameError("Bad_Name", pattern, [])).toMatch(/lowercase/);
    expect(nameError("shopflow", pattern, ["shopflow"])).toMatch(/read-only/);
    expect(nameError("auction-checklist", pattern, ["shopflow"])).toBeNull();
  });
});

describe("format", () => {
  it("formats numbers", () => {
    expect(formatMs(1500)).toBe("1.5 s");
    expect(formatMs(26.4)).toBe("26 ms");
    expect(formatMs(4.25)).toBe("4.3 ms");
    expect(formatBytes(1_400_000)).toBe("1.4 MB");
    expect(formatBytes(40_047)).toBe("40.0 KB");
    expect(formatBytes(900)).toBe("900 B");
    expect(metric(0.81481)).toBe("0.815");
    expect(metric(null)).toBe("—");
    expect(percent(0.977)).toBe("98 %");
    expect(percent(null)).toBe("—");
    expect(lineRange(3, 3)).toBe("3");
    expect(lineRange(3, 9)).toBe("3–9");
    expect(formatDuration(45)).toBe("45 s");
    expect(formatDuration(125)).toBe("2 min 5 s");
    expect(formatDuration(18_000)).toBe("about 5 h");
  });
  it("formats dates and expiry", () => {
    const now = Date.parse("2026-10-07T12:00:00Z");
    expect(expiresIn("2026-10-08T11:00:00Z", now)).toBe("expires in 23 h");
    expect(expiresIn("2026-10-07T12:40:00Z", now)).toBe("expires in 40 min");
    expect(expiresIn("2026-10-07T11:00:00Z", now)).toBe("expired");
    expect(expiresIn("nope", now)).toBe("");
    expect(formatDate("2026-10-06T00:26:57+00:00")).toBe("2026-10-06 00:26 UTC");
    expect(formatDate("2026-10-07 15:32:37")).toMatch(/^2026-10-07/);
    expect(formatDate("garbage")).toBe("garbage");
  });
  it("labels categories and modes", () => {
    expect(categoryLabel("multi_file")).toBe("Multi-file");
    expect(categoryLabel("other")).toBe("other");
    expect(modeLabel("hybrid_rerank")).toBe("Hybrid + rerank");
    expect(modeLabel("x")).toBe("x");
  });
});
