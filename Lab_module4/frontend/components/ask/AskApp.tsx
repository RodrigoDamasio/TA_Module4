"use client";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import ErrorBanner from "@/components/ErrorBanner";
import { useApiError } from "@/hooks/useApiError";
import { useLoad } from "@/hooks/useLoad";
import {
  ApiError,
  builtinDataset,
  config,
  listCodebases,
  type QueryParams,
  query,
  search,
} from "@/lib/api";
import { formatDuration } from "@/lib/format";
import {
  type Example,
  QueryResultSchema,
  type SearchMode,
  SearchResultSchema,
} from "@/lib/schemas";
import Composer from "./Composer";
import QuerySettings from "./QuerySettings";
import Suggestions from "./Suggestions";
import TurnView from "./TurnView";
import type { Turn, TurnKind } from "./types";

const STORAGE_KEY = "codebase-rag.turns.v1";
const MAX_SAVED = 20;
const MODEL_RETRIES = 3;
const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** Saved turns are re-validated: storage is never trusted more than the network. */
function readSaved(): Turn[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed.flatMap((t: Turn) => {
      const schema = t?.kind === "search" ? SearchResultSchema : QueryResultSchema;
      const result = schema.safeParse(t?.result);
      return t?.status === "done" && result.success ? [{ ...t, result: result.data }] : [];
    });
  } catch {
    return [];
  }
}

interface Props {
  initialCodebases: string[] | null;
  initialMode: SearchMode | null;
  initialK: number | null;
}

export default function AskApp({ initialCodebases, initialMode, initialK }: Props) {
  const router = useRouter();
  const cfg = useLoad(config);
  const cbs = useLoad(listCodebases);
  const dataset = useLoad(builtinDataset);
  const [selected, setSelected] = useState<string[] | null>(initialCodebases);
  const [mode, setMode] = useState<SearchMode | null>(initialMode);
  const [k, setK] = useState<number | null>(initialK);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [searchOnly, setSearchOnly] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false); // the summary line shows the values
  const [announcement, setAnnouncement] = useState("");
  const [lastFailed, setLastFailed] = useState<Turn | null>(null);
  const { error, cooldown, fail, clear } = useApiError();
  const composer = useRef<HTMLTextAreaElement>(null);
  const counter = useRef(0);

  // Effective settings: URL/user choice, else the server's defaults; unknown codebases dropped.
  const known = cbs.data?.map((c) => c.id) ?? null;
  const wanted = selected ?? cbs.data?.filter((c) => c.kind === "sample").map((c) => c.id) ?? [];
  const active = known ? wanted.filter((id) => known.includes(id)) : wanted;
  const dropped = known && selected ? selected.filter((id) => !known.includes(id)) : [];
  const defaults = cfg.data?.defaults;
  const activeMode: SearchMode = mode ?? defaults?.mode ?? "hybrid";
  const maxK = cfg.data?.limits.max_k ?? 10;
  const activeK = Math.min(maxK, Math.max(1, k ?? defaults?.k ?? 5));
  const activeKey = active.join(",");

  // Restore the conversation after mount: sessionStorage doesn't exist on the server.
  useEffect(() => {
    let alive = true;
    const saved = readSaved(); // read before the save effect below writes
    Promise.resolve().then(() => {
      if (alive && saved.length > 0) setTurns(saved);
    });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    try {
      const done = turns.filter((t) => t.status === "done").slice(-MAX_SAVED);
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(done));
    } catch {
      // Private mode or full storage: the conversation just won't survive a reload.
    }
  }, [turns]);

  // Keep the settings in the URL once the user (or the URL) chose them.
  useEffect(() => {
    if (selected === null && mode === null && k === null) return;
    const params = new URLSearchParams({ cb: activeKey, mode: activeMode, k: String(activeK) });
    window.history.replaceState(null, "", `?${params}`);
  }, [selected, mode, k, activeKey, activeMode, activeK]);

  // "/" focuses the composer when the focus is not in a field.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      if (e.key !== "/" || target?.closest("input, textarea, select, [contenteditable]")) return;
      e.preventDefault();
      composer.current?.focus();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const pending = turns.some((t) => t.status === "pending");
  const minChars = searchOnly ? 2 : 3;
  let disabledReason: string | null = null;
  if (!cfg.data) disabledReason = "Loading settings…";
  else if (pending) disabledReason = "Wait for the current answer.";
  else if (cooldown > 0) disabledReason = `Try again in ${formatDuration(cooldown)}.`;
  else if (active.length === 0) disabledReason = "Choose at least one codebase.";
  else if (question.trim().length < minChars) disabledReason = "Type a question.";

  async function execute(turn: Turn, attempt = 0): Promise<void> {
    try {
      const result =
        turn.kind === "query"
          ? await query(turn.question, turn.params)
          : await search(turn.question, turn.params);
      setTurns((ts) => ts.map((t) => (t.id === turn.id ? { ...t, status: "done", result } : t)));
      const n = "answer" in result ? result.sources.length : result.hits.length;
      setAnnouncement(turn.kind === "query" ? `Answer ready, ${n} sources.` : `${n} chunks found.`);
    } catch (err) {
      if (err instanceof ApiError && err.kind === "loading" && attempt < MODEL_RETRIES) {
        setAnnouncement("The search models are starting. Retrying in a few seconds…");
        await sleep((err.retryAfter ?? 3) * 1000);
        return execute(turn, attempt + 1);
      }
      const message = err instanceof ApiError ? err.message : "Something went wrong.";
      setTurns((ts) =>
        ts.map((t) => (t.id === turn.id ? { ...t, status: "error", error: message } : t)),
      );
      setLastFailed(turn);
      fail(err);
      if (err instanceof ApiError && err.kind === "not_found") cbs.reload();
    }
  }

  function submit(text: string, kind: TurnKind, params?: QueryParams) {
    const turn: Turn = {
      id: `t${Date.now().toString(36)}${counter.current++}`,
      kind,
      question: text.trim(),
      params: params ?? { codebases: active, k: activeK, mode: activeMode },
      status: "pending",
    };
    clear();
    setLastFailed(null);
    setTurns((ts) => [...ts, turn]);
    setQuestion("");
    setSettingsOpen(false);
    void execute(turn);
  }

  function pick(example: Example) {
    if (!defaults) return;
    setSelected(example.codebases);
    setMode(defaults.mode);
    setK(defaults.k);
    // Same codebases, K and mode as the evaluation: the server answers from its cache.
    submit(example.question, "query", { codebases: example.codebases, k: defaults.k, mode: defaults.mode });
  }

  const actions: { label: string; onClick: () => void }[] = [];
  if (error?.kind === "quota" && lastFailed) {
    actions.push({ label: "Search instead", onClick: () => submit(lastFailed.question, "search", lastFailed.params) });
  }
  if (error?.kind === "empty") actions.push({ label: "Go to Codebases", onClick: () => router.push("/codebases") });

  const loadError = cfg.error ?? cbs.error;

  return (
    <div className="flex flex-1 flex-col gap-4">
      {loadError && (
        <ErrorBanner
          error={loadError}
          cooldown={0}
          actions={[{ label: "Retry", onClick: () => { cfg.reload(); cbs.reload(); } }]}
        />
      )}
      {cfg.data && cbs.data && (
        <QuerySettings
          config={cfg.data}
          codebases={cbs.data}
          selected={active}
          mode={activeMode}
          k={activeK}
          open={settingsOpen}
          onToggle={setSettingsOpen}
          onSelected={setSelected}
          onMode={setMode}
          onK={setK}
        />
      )}
      {dropped.length > 0 && (
        <p role="status" className="text-sm text-zinc-600 dark:text-zinc-400">
          Not found and removed from the selection: {dropped.join(", ")}.
        </p>
      )}

      <section aria-label="Conversation" className="flex-1 space-y-8">
        {turns.map((t) => (
          <TurnView key={t.id} turn={t} />
        ))}
      </section>

      {turns.length === 0 && dataset.data && (
        <Suggestions examples={dataset.data} disabled={!defaults || pending || cooldown > 0} onPick={pick} />
      )}

      {error && <ErrorBanner error={error} cooldown={cooldown} actions={actions} />}
      <div className="sr-only" role="status" aria-live="polite">
        {announcement}
      </div>

      <Composer
        ref={composer}
        value={question}
        maxChars={cfg.data?.limits.question_max_chars ?? 500}
        searchOnly={searchOnly}
        disabledReason={disabledReason}
        busy={pending}
        onChange={setQuestion}
        onSearchOnly={setSearchOnly}
        onSubmit={() => submit(question, searchOnly ? "search" : "query")}
      />
      {turns.length > 0 && !pending && (
        <button
          type="button"
          onClick={() => {
            setTurns([]);
            clear();
          }}
          className="self-start text-xs text-zinc-600 underline dark:text-zinc-400"
        >
          Clear conversation
        </button>
      )}
    </div>
  );
}
