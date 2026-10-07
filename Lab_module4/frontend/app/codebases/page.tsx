import CodebasesApp from "@/components/codebases/CodebasesApp";

export default function CodebasesPage() {
  return (
    <main className="flex flex-col gap-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Codebases</h1>
        <p className="max-w-3xl text-sm text-zinc-600 dark:text-zinc-400">
          Index your own code, or explore the two samples. Files are split into chunks along
          functions and classes, embedded locally on the server, and searchable by meaning and by
          exact words.
        </p>
      </header>
      <CodebasesApp />
    </main>
  );
}
