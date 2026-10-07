import AskApp from "@/components/ask/AskApp";
import { SEARCH_MODES, type SearchMode } from "@/lib/schemas";

type Params = Promise<{ [key: string]: string | string[] | undefined }>;

export default async function AskPage({ searchParams }: { searchParams: Params }) {
  const { cb, mode, k } = await searchParams;
  const codebases = typeof cb === "string" ? cb.split(",").filter(Boolean).slice(0, 10) : null;
  const initialMode = SEARCH_MODES.includes(mode as SearchMode) ? (mode as SearchMode) : null;
  const initialK = typeof k === "string" && /^\d{1,2}$/.test(k) ? Number(k) : null;
  return (
    <main className="flex flex-1 flex-col gap-4">
      <h1 className="sr-only">Ask about the code</h1>
      <AskApp initialCodebases={codebases} initialMode={initialMode} initialK={initialK} />
    </main>
  );
}
