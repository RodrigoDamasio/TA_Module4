"use client";
import { useLoad } from "@/hooks/useLoad";
import { health } from "@/lib/api";

/** Server state in words: "Server ready · reranker disabled". */
export default function HealthDot() {
  const { data, error } = useLoad(health);
  let text = "Checking server…";
  let color = "bg-zinc-400";
  if (error) {
    text = "Server unreachable";
    color = "bg-red-600";
  } else if (data) {
    const ready = data.models === "ready";
    text = ready ? "Server ready" : `Models ${data.models}`;
    if (data.reranker && data.reranker !== "ready") text += ` · reranker ${data.reranker}`;
    color = ready ? "bg-emerald-600" : "bg-amber-500";
  }
  return (
    <p className="flex items-center gap-2 text-xs text-zinc-600 dark:text-zinc-400" role="status">
      <span aria-hidden="true" className={`inline-block h-2 w-2 rounded-full ${color}`} />
      {text}
    </p>
  );
}
