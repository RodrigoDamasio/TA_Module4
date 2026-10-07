"use client";
import ErrorBanner from "@/components/ErrorBanner";
import { useLoad } from "@/hooks/useLoad";
import { config, listCodebases } from "@/lib/api";
import CodebaseList from "./CodebaseList";
import UploadPanel from "./UploadPanel";

export default function CodebasesApp() {
  const cfg = useLoad(config);
  const cbs = useLoad(listCodebases);
  const loadError = cfg.error ?? cbs.error;
  return (
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      {loadError && (
        <ErrorBanner error={loadError} cooldown={0} actions={[{ label: "Retry", onClick: () => { cfg.reload(); cbs.reload(); } }]} />
      )}
      <section aria-labelledby="list-title" className="space-y-3">
        <h2 id="list-title" className="text-lg font-semibold">
          Indexed codebases
        </h2>
        {cbs.data ? (
          <CodebaseList codebases={cbs.data} config={cfg.data} onChanged={cbs.reload} />
        ) : (
          !loadError && <p className="text-sm text-zinc-600 dark:text-zinc-400">Loading…</p>
        )}
      </section>
      <section aria-labelledby="upload-title" className="space-y-3">
        <h2 id="upload-title" className="text-lg font-semibold">
          Index your code
        </h2>
        {cfg.data && cbs.data && <UploadPanel config={cfg.data} codebases={cbs.data} onIndexed={cbs.reload} />}
      </section>
    </div>
  );
}
