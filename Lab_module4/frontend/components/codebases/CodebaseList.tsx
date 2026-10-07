"use client";
import Link from "next/link";
import { useState } from "react";
import Badge from "@/components/Badge";
import ErrorBanner from "@/components/ErrorBanner";
import { useApiError } from "@/hooks/useApiError";
import { useNow } from "@/hooks/useNow";
import { deleteCodebase } from "@/lib/api";
import { expiresIn, formatBytes } from "@/lib/format";
import type { Codebase, Config } from "@/lib/schemas";

export default function CodebaseList({
  codebases,
  config,
  onChanged,
}: {
  codebases: Codebase[];
  config: Config | null;
  onChanged: () => void;
}) {
  const now = useNow();
  const [confirming, setConfirming] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const { error, cooldown, fail, clear } = useApiError();
  const sorted = [...codebases].sort((a, b) => (a.kind === b.kind ? a.id.localeCompare(b.id) : a.kind === "sample" ? -1 : 1));
  const users = codebases.filter((c) => c.kind === "user").length;

  async function remove(id: string) {
    setDeleting(id);
    clear();
    try {
      await deleteCodebase(id);
      setConfirming(null);
      onChanged();
    } catch (err) {
      fail(err);
    } finally {
      setDeleting(null);
    }
  }

  return (
    <div className="space-y-3">
      {config && (
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          {users} of {config.limits.max_user_codebases} upload slots used. Uploads expire after{" "}
          {config.limits.codebase_ttl_hours} hours.
        </p>
      )}
      {error && <ErrorBanner error={error} cooldown={cooldown} />}
      <ul className="space-y-2">
        {sorted.map((c) => (
          <li key={c.id} className="rounded-md border border-zinc-200 p-3 dark:border-zinc-800">
            <div className="flex flex-wrap items-center gap-2">
              <Link href={`/codebases/${encodeURIComponent(c.id)}`} className="font-medium text-orange-800 underline dark:text-orange-300">
                {c.id}
              </Link>
              {c.read_only ? <Badge>sample · read-only</Badge> : <Badge tone="accent">uploaded</Badge>}
              {c.expires_at && now !== null && <span className="text-xs text-zinc-600 dark:text-zinc-400">{expiresIn(c.expires_at, now)}</span>}
            </div>
            <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
              {c.file_count} files · {c.chunk_count} chunks · {formatBytes(c.bytes)} ·{" "}
              {Object.entries(c.languages).map(([lang, n]) => `${lang} ${n}`).join(", ")}
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-3 text-sm">
              <Link href={`/?cb=${encodeURIComponent(c.id)}`} className="font-medium text-orange-800 underline dark:text-orange-300">
                Ask about it
              </Link>
              {!c.read_only &&
                (confirming === c.id ? (
                  <span className="flex flex-wrap items-center gap-2">
                    <span>Delete {c.id} and its {c.chunk_count} chunks?</span>
                    <button type="button" disabled={deleting === c.id} onClick={() => remove(c.id)} className="font-medium text-red-800 underline dark:text-red-300">
                      Confirm delete
                    </button>
                    <button type="button" onClick={() => setConfirming(null)} className="underline">
                      Cancel
                    </button>
                  </span>
                ) : (
                  <button type="button" onClick={() => setConfirming(c.id)} className="text-red-800 underline dark:text-red-300">
                    Delete
                  </button>
                ))}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
