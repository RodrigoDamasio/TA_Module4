import EvaluationApp from "@/components/evaluation/EvaluationApp";

export default function EvaluationPage() {
  return (
    <main className="flex flex-col gap-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Evaluation</h1>
        <p className="max-w-3xl text-sm text-zinc-600 dark:text-zinc-400">
          How well the system finds the right code and answers from it, measured on 20 questions
          about the two sample codebases. Reading the reports and running them here costs no AI
          calls.
        </p>
      </header>
      <EvaluationApp />
    </main>
  );
}
