"use client";
import { forwardRef } from "react";

interface Props {
  value: string;
  maxChars: number;
  searchOnly: boolean;
  disabledReason: string | null;
  busy: boolean;
  onChange: (value: string) => void;
  onSearchOnly: (value: boolean) => void;
  onSubmit: () => void;
}

const Composer = forwardRef<HTMLTextAreaElement, Props>(function Composer(p, ref) {
  const length = p.value.length;
  const disabled = p.disabledReason !== null;
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!disabled) p.onSubmit();
      }}
      className="sticky bottom-0 space-y-2 border-t border-zinc-200 bg-[var(--background)] pt-3 pb-2 dark:border-zinc-800"
    >
      <label htmlFor="question" className="sr-only">
        {p.searchOnly ? "Search the code" : "Ask about the code"}
      </label>
      <textarea
        id="question"
        ref={ref}
        rows={2}
        value={p.value}
        maxLength={p.maxChars}
        onChange={(e) => p.onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (!disabled) p.onSubmit();
          }
        }}
        placeholder={p.searchOnly ? "Search the code, e.g. apply discount" : "Ask about the code, e.g. How are passwords hashed?"}
        className="w-full resize-y rounded-md border border-zinc-300 bg-white p-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
        aria-describedby="composer-hint"
      />
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="submit"
          disabled={disabled}
          aria-busy={p.busy}
          className="rounded-md bg-orange-700 px-4 py-1.5 text-sm font-medium text-white hover:bg-orange-800 disabled:bg-zinc-400 dark:disabled:bg-zinc-700"
        >
          {p.searchOnly ? "Search" : "Ask"}
        </button>
        <label className="flex items-center gap-1.5 text-sm">
          <input type="checkbox" checked={p.searchOnly} onChange={(e) => p.onSearchOnly(e.target.checked)} />
          Search only (no AI call)
        </label>
        <span id="composer-hint" className="text-xs text-zinc-600 dark:text-zinc-400">
          {p.disabledReason && length > 0 ? p.disabledReason : "Enter to send, Shift+Enter for a new line."}{" "}
          {length}/{p.maxChars}
        </span>
      </div>
    </form>
  );
});

export default Composer;
