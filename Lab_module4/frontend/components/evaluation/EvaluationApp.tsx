"use client";
import { useState } from "react";
import ErrorBanner from "@/components/ErrorBanner";
import Tabs from "@/components/Tabs";
import { useLoad } from "@/hooks/useLoad";
import { config, getGrid, getReport } from "@/lib/api";
import GridView from "./GridView";
import ReportView from "./ReportView";
import RunPanel from "./RunPanel";
import StatsView from "./StatsView";

const TABS = [
  { id: "report", label: "Report" },
  { id: "grid", label: "Comparison grid" },
  { id: "run", label: "Run" },
  { id: "server", label: "Server" },
];

function StoredReport() {
  const { data, error, reload } = useLoad(() => getReport("full"));
  if (error) return <ErrorBanner error={error} cooldown={0} actions={[{ label: "Retry", onClick: reload }]} />;
  return data ? <ReportView report={data} /> : <p className="text-sm">Loading the report…</p>;
}

function Grid() {
  const { data, error, reload } = useLoad(getGrid);
  if (error) return <ErrorBanner error={error} cooldown={0} actions={[{ label: "Retry", onClick: reload }]} />;
  return data ? <GridView grid={data} /> : <p className="text-sm">Loading the grid…</p>;
}

function Run() {
  const { data, error, reload } = useLoad(config);
  if (error) return <ErrorBanner error={error} cooldown={0} actions={[{ label: "Retry", onClick: reload }]} />;
  return data ? <RunPanel config={data} /> : <p className="text-sm">Loading…</p>;
}

export default function EvaluationApp() {
  const [tab, setTab] = useState("report");
  return (
    <Tabs tabs={TABS} active={tab} onChange={setTab} label="Evaluation views">
      {tab === "report" && <StoredReport />}
      {tab === "grid" && <Grid />}
      {tab === "run" && <Run />}
      {tab === "server" && <StatsView />}
    </Tabs>
  );
}
