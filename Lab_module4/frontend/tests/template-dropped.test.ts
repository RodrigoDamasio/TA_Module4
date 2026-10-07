import { describe, expect, it } from "vitest";
import { fromDrop } from "@/lib/dropped";
import { DATASET_TEMPLATE, parseDataset } from "@/lib/template";

describe("custom dataset parsing", () => {
  it("accepts the template", () => {
    expect(parseDataset(JSON.stringify(DATASET_TEMPLATE), 30)).toEqual({ examples: DATASET_TEMPLATE });
  });
  it.each([
    ["{", /Not valid JSON/],
    ["{}", /JSON list/],
    ["[]", /1 to 30/],
    ["[1]", /Example 1 is not an object/],
    ['[{"id":"a","question":"q","category":"symbol"}]', /no "codebases"/],
    ['[{"id":"a","question":"q","category":"vibes","codebases":[]}]', /category must be one of/],
  ])("%s is refused", (text, message) => {
    const r = parseDataset(text, 30);
    expect("error" in r && r.error).toMatch(message);
  });
});

function fileEntry(name: string, text: string) {
  const file = new File([text], name);
  return { isFile: true, isDirectory: false, name, file: (ok: (f: File) => void) => ok(file) };
}
function dirEntry(name: string, children: unknown[]) {
  let read = false;
  return {
    isFile: false,
    isDirectory: true,
    name,
    createReader: () => ({ readEntries: (ok: (e: unknown[]) => void) => { ok(read ? [] : children); read = true; } }),
  };
}
const transfer = (entries: unknown[], files: File[] = []) =>
  ({ items: entries.map((e) => ({ webkitGetAsEntry: () => e })), files }) as unknown as DataTransfer;

describe("dropped folders", () => {
  it("walks a dropped folder and strips its name", async () => {
    const drop = transfer([dirEntry("Shop", [fileEntry("a.py", "x"), dirEntry("web", [fileEntry("b.ts", "yy")])])]);
    const { candidates, folder } = await fromDrop(drop);
    expect(folder).toBe("Shop");
    expect(candidates.map((c) => [c.path, c.size])).toEqual([["a.py", 1], ["web/b.ts", 2]]);
    expect(await candidates[1].read()).toBe("yy");
  });
  it("keeps paths for several dropped items, and falls back to plain files", async () => {
    const two = await fromDrop(transfer([fileEntry("a.py", "x"), fileEntry("b.py", "x")]));
    expect(two).toMatchObject({ folder: null });
    expect(two.candidates.map((c) => c.path)).toEqual(["a.py", "b.py"]);
    const plain = await fromDrop({ items: [], files: [new File(["z"], "c.py")] } as unknown as DataTransfer);
    expect(plain.candidates[0].path).toBe("c.py");
  });
});
