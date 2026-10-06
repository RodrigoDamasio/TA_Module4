import type { Entry } from "./entries";

export interface Balance {
  account: string | null;
  balanceCents: number;
  credits: number;
  debits: number;
}

/**
 * Sums the entries of one account. Returns the balance in integer cents plus how many
 * credit and debit entries it contains. An empty list gives a zero balance.
 */
export function computeBalance(entries: Entry[]): Balance {
  return {
    account: entries[0]?.account ?? null,
    balanceCents: entries.reduce((sum, e) => sum + e.amountCents, 0),
    credits: entries.filter((e) => e.amountCents > 0).length,
    debits: entries.filter((e) => e.amountCents < 0).length,
  };
}
