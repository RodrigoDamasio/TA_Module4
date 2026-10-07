"use client";
import Link from "next/link";
import { useState } from "react";
import Badge from "@/components/Badge";
import CodeBlock from "@/components/CodeBlock";
import ErrorBanner from "@/components/ErrorBanner";
import { useLoad } from "@/hooks/useLoad";
import { useNow } from "@/hooks/useNow";
import { getCodebase, listChunks } from "@/lib/api";
import { expiresIn, formatBytes, lineRange } from "@/lib/format";

function ChunkViewer({ codebase, path }: { codebase: string; path: string }) {
  const { data, error } = useLoad(() => listChunks(codebase, path));
  if (error) return <ErrorBanner error={error} cooldown={0} />;
  if (!data) return <p className="text-sm">Loading chunks…</p>;
  return (
    <section aria-labelledby="chunks-title" className="space-y-3">
      <h2 id="chunks-title" className="text-lg font-semibold">
        <span className="font-mono text-base break-all">{path}</span>: {data.length} chunk{data.length === 1 ? "" : "s"}
      </h2>
      <p className="text-sm text-zinc-600 dark:text-zinc-400">
        How this file was split. Each chunk is embedded with a header naming its file and symbols, so a
        function body still says where it belongs.
      </p>
      <ol className="space-y-3">
        {data.map((c, i) => (
          <li key={c.chunk_id} className="space-y-1">
            <p className="flex flex-wrap items-center gap-2 text-sm">
              <span className="font-medium">Chunk {i + 1}</span>
              <Badge>{c.kind}</Badge>
              <span className="font-mono text-xs">lines {lineRange(c.start_line, c.end_line)}</span>
              {c.part && <Badge>part {c.part[0]}/{c.part[1]}</Badge>}
              {c.symbol && <span className="text-xs text-zinc-600 dark:text-zinc-400">{c.symbol}</span>}
            </p>
            <CodeBlock code={c.code} startLine={c.start_line} label={`Chunk ${i + 1} of ${path}`} />
          </li>
        ))}
      </ol>
    </section>
  );
}

export default function CodebaseView({ id }: { id: string }) {
  const { data, error } = useLoad(() => getCodebase(id));
  const now = useNow();
  const [path, setPath] = useState<string | null>(null);

  if (error) {
    return (
      <div className="space-y-3">
        <h1 className="text-2xl font-semibold">{id}</h1>
        <ErrorBanner error={error} cooldown={0} />
        <Link href="/codebases" className="text-sm font-medium text-orange-800 underline dark:text-orange-300">
          Back to codebases
        </Link>
      </div>
    );
  }
  if (!data) return <p className="text-sm">Loading…</p>;

  return (
    <>
      <header className="space-y-2">
        <p className="text-sm">
          <Link href="/codebases" className="text-orange-800 underline dark:text-orange-300">Codebases</Link> / {data.id}
        </p>
        <h1 className="flex flex-wrap items-center gap-2 text-2xl font-semibold tracking-tight">
          {data.id}
          {data.read_only ? <Badge>sample · read-only</Badge> : <Badge tone="accent">uploaded</Badge>}
        </h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          {data.file_count} files · {data.chunk_count} chunks · {formatBytes(data.bytes)}
          {data.expires_at && now !== null && ` · ${expiresIn(data.expires_at, now)}`}
        </p>
        <Link href={`/?cb=${encodeURIComponent(data.id)}`} className="inline-block text-sm font-medium text-orange-800 underline dark:text-orange-300">
          Ask about this codebase
        </Link>
      </header>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <section aria-labelledby="files-title" className="space-y-2">
          <h2 id="files-title" className="text-lg font-semibold">Files</h2>
          <div role="region" aria-label="Files" tabIndex={0} className="max-h-[32rem] overflow-auto rounded border border-zinc-200 dark:border-zinc-800">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Indexed files</caption>
              <thead className="sticky top-0 bg-zinc-100 text-xs dark:bg-zinc-900">
                <tr>
                  <th scope="col" className="px-2 py-1">Path</th>
                  <th scope="col" className="px-2 py-1">Language</th>
                  <th scope="col" className="px-2 py-1 text-right">Chunks</th>
                </tr>
              </thead>
              <tbody>
                {data.files.map((f) => (
                  <tr key={f.path} className={`border-t border-zinc-200 dark:border-zinc-800 ${f.path === path ? "bg-orange-50 dark:bg-orange-950" : ""}`}>
                    <td className="px-2 py-1">
                      <button type="button" onClick={() => setPath(f.path)} aria-pressed={f.path === path} className="text-left font-mono text-xs break-all text-orange-800 underline dark:text-orange-300">
                        {f.path}
                      </button>
                      {f.fallback && <span className="ml-1"><Badge tone="warn" title="Parsed with the generic splitter">fallback chunking</Badge></span>}
                    </td>
                    <td className="px-2 py-1 text-xs">{f.language}</td>
                    <td className="px-2 py-1 text-right text-xs">{f.chunk_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <div>
          {path ? (
            <ChunkViewer key={path} codebase={data.id} path={path} />
          ) : (
            <p className="text-sm text-zinc-600 dark:text-zinc-400">Choose a file to see how it was split into chunks.</p>
          )}
        </div>
      </div>
    </>
  );
}
