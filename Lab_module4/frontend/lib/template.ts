/** A custom retrieval dataset template in the format POST /evaluate accepts
 * (backend app/application/evaluation/relevance.py). */
export const DATASET_TEMPLATE = [
  {
    id: "my-1",
    category: "symbol",
    question: "What does the processOrder function do?",
    codebases: ["shopflow"],
    relevant: [{ codebase: "shopflow", path: "web/src/orders/processOrder.ts", symbol: "processOrder" }],
  },
  {
    id: "my-2",
    category: "unanswerable",
    question: "How is Redis caching configured?",
    codebases: ["shopflow"],
    relevant: [],
    expect_found: false,
  },
];

export const CATEGORIES = ["symbol", "conceptual", "location", "multi_file", "cross_codebase", "unanswerable"];

/** Parses pasted JSON into a list of examples, or explains what is wrong. */
export function parseDataset(text: string, max: number): { examples: unknown[] } | { error: string } {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch (err) {
    return { error: `Not valid JSON: ${err instanceof Error ? err.message : "parse error"}.` };
  }
  if (!Array.isArray(data)) return { error: "The dataset must be a JSON list of examples." };
  if (data.length === 0 || data.length > max) return { error: `Send 1 to ${max} examples (got ${data.length}).` };
  for (const [i, e] of data.entries()) {
    if (typeof e !== "object" || e === null) return { error: `Example ${i + 1} is not an object.` };
    const ex = e as Record<string, unknown>;
    for (const field of ["id", "question", "category", "codebases"]) {
      if (!(field in ex)) return { error: `Example ${i + 1} has no "${field}".` };
    }
    if (!CATEGORIES.includes(String(ex.category))) {
      return { error: `Example ${i + 1}: category must be one of ${CATEGORIES.join(", ")}.` };
    }
  }
  return { examples: data };
}
