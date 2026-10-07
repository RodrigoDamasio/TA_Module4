"use client";
import { useId, useRef } from "react";

interface Tab {
  id: string;
  label: string;
}

/** WAI-ARIA tabs: arrow keys, Home/End, aria-selected; the panel is rendered by the parent. */
export default function Tabs({
  tabs,
  active,
  onChange,
  label,
  children,
}: {
  tabs: Tab[];
  active: string;
  onChange: (id: string) => void;
  label: string;
  children: React.ReactNode;
}) {
  const base = useId();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const index = Math.max(0, tabs.findIndex((t) => t.id === active));

  function onKeyDown(e: React.KeyboardEvent) {
    const moves: Record<string, number> = {
      ArrowRight: (index + 1) % tabs.length,
      ArrowLeft: (index - 1 + tabs.length) % tabs.length,
      Home: 0,
      End: tabs.length - 1,
    };
    const next = moves[e.key];
    if (next === undefined) return;
    e.preventDefault();
    onChange(tabs[next].id);
    refs.current[next]?.focus();
  }

  return (
    <div>
      <div role="tablist" aria-label={label} className="flex flex-wrap gap-1 border-b border-zinc-200 dark:border-zinc-800">
        {tabs.map((t, i) => (
          <button
            key={t.id}
            ref={(el) => {
              refs.current[i] = el;
            }}
            role="tab"
            type="button"
            id={`${base}-tab-${t.id}`}
            aria-selected={t.id === active}
            aria-controls={`${base}-panel`}
            tabIndex={t.id === active ? 0 : -1}
            onClick={() => onChange(t.id)}
            onKeyDown={onKeyDown}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
              t.id === active
                ? "border-orange-700 text-orange-800 dark:border-orange-400 dark:text-orange-300"
                : "border-transparent text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`${base}-panel`} aria-labelledby={`${base}-tab-${active}`} className="pt-4">
        {children}
      </div>
    </div>
  );
}
