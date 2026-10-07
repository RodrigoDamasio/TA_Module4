import CodebaseView from "@/components/codebases/CodebaseView";

export default async function CodebasePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <main className="flex flex-col gap-6">
      <CodebaseView id={decodeURIComponent(id)} />
    </main>
  );
}
