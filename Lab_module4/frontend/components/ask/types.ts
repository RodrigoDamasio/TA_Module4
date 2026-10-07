import type { QueryParams } from "@/lib/api";
import type { QueryResult, SearchResult } from "@/lib/schemas";

export type TurnKind = "query" | "search";

export interface Turn {
  id: string;
  kind: TurnKind;
  question: string;
  params: QueryParams;
  status: "pending" | "done" | "error";
  result?: QueryResult | SearchResult;
  error?: string;
}

export const isQueryResult = (r: QueryResult | SearchResult): r is QueryResult => "answer" in r;
