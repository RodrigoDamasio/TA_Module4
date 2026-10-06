import { z } from "zod";
import { store } from "./db";

/** A ledger entry: amounts are integer cents, positive for credits, negative for debits. */
export const EntrySchema = z.object({
  account: z.string().min(1).max(64),
  amountCents: z.number().int().refine((n) => n !== 0, "amount must not be zero"),
  description: z.string().max(200),
  bookedAt: z.string().datetime(),
});

export type Entry = z.infer<typeof EntrySchema> & { id: string };

/** Validates the body with EntrySchema and stores the entry with a generated id. */
export function createEntry(body: unknown): { ok: true; entry: Entry } | { ok: false; errors: string[] } {
  const parsed = EntrySchema.safeParse(body);
  if (!parsed.success) return { ok: false, errors: parsed.error.issues.map((i) => i.message) };
  const entry = { ...parsed.data, id: crypto.randomUUID() };
  store.entries.push(entry);
  return { ok: true, entry };
}

export function listEntries(account?: string): Entry[] {
  return account ? store.entries.filter((e) => e.account === account) : [...store.entries];
}
