/** Code as text with real line numbers. Scrolls inside its own box (focusable for keyboards). */
export default function CodeBlock({
  code,
  startLine = 1,
  label,
  maxHeight = "max-h-80",
  lineNumbers = true,
}: {
  code: string;
  startLine?: number;
  label: string;
  maxHeight?: string;
  lineNumbers?: boolean;
}) {
  const lines = code.replace(/\n$/, "").split("\n");
  const width = String(startLine + lines.length - 1).length;
  return (
    <div
      role="region"
      aria-label={label}
      tabIndex={0}
      className={`${maxHeight} overflow-auto rounded border border-zinc-200 bg-zinc-50 text-xs dark:border-zinc-800 dark:bg-zinc-900`}
    >
      <pre className="p-2 font-mono leading-5">
        {lines.map((line, i) => (
          <div key={i} className="flex">
            {lineNumbers && (
              <span
                aria-hidden="true"
                className="mr-3 shrink-0 text-right text-zinc-500 select-none"
                style={{ minWidth: `${width}ch` }}
              >
                {startLine + i}
              </span>
            )}
            <code className="whitespace-pre">{line || " "}</code>
          </div>
        ))}
      </pre>
    </div>
  );
}
