"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import HealthDot from "./HealthDot";

const LINKS = [
  { href: "/", label: "Ask" },
  { href: "/codebases", label: "Codebases" },
  { href: "/evaluation", label: "Evaluation" },
];

export default function Nav() {
  const pathname = usePathname();
  const current = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));
  return (
    <header className="border-b border-zinc-200 dark:border-zinc-800">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
        <Link href="/" className="font-semibold tracking-tight">
          Codebase RAG
        </Link>
        <nav aria-label="Main">
          <ul className="flex gap-1">
            {LINKS.map((l) => (
              <li key={l.href}>
                <Link
                  href={l.href}
                  aria-current={current(l.href) ? "page" : undefined}
                  className={`rounded px-3 py-1.5 text-sm font-medium ${
                    current(l.href)
                      ? "bg-orange-50 text-orange-800 dark:bg-orange-950 dark:text-orange-200"
                      : "text-zinc-700 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800"
                  }`}
                >
                  {l.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <div className="ml-auto">
          <HealthDot />
        </div>
      </div>
    </header>
  );
}
