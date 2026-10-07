/** Splits an answer into text, inline code and [n] citations. The marker grammar is the
 * backend's (domain/answers.py): "[2]", and the grouped forms "[1, 2]" and "[1,3]". */

export type Segment =
  | { type: "text"; text: string }
  | { type: "code"; text: string }
  | { type: "cite"; numbers: number[] };

const MARKER = /\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]/g;
const INLINE_CODE = /`([^`\n]+)`/g;

function splitCode(text: string): Segment[] {
  const out: Segment[] = [];
  let last = 0;
  for (const m of text.matchAll(INLINE_CODE)) {
    if (m.index > last) out.push({ type: "text", text: text.slice(last, m.index) });
    out.push({ type: "code", text: m[1] });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ type: "text", text: text.slice(last) });
  return out;
}

export function splitAnswer(answer: string): Segment[] {
  const out: Segment[] = [];
  let last = 0;
  for (const m of answer.matchAll(MARKER)) {
    if (m.index > last) out.push(...splitCode(answer.slice(last, m.index)));
    out.push({ type: "cite", numbers: m[1].split(",").map((n) => Number(n.trim())) });
    last = m.index + m[0].length;
  }
  if (last < answer.length) out.push(...splitCode(answer.slice(last)));
  return out;
}

/** Every number cited in the text, in order of first appearance. */
export function citedNumbers(answer: string): number[] {
  const seen: number[] = [];
  for (const seg of splitAnswer(answer)) {
    if (seg.type !== "cite") continue;
    for (const n of seg.numbers) if (!seen.includes(n)) seen.push(n);
  }
  return seen;
}
