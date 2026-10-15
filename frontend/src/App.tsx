import { useCallback, useEffect, useMemo, useState } from "react";
import { ReportCard } from "./components/ReportCard";
import { useSocket, type SocketStatus } from "./hooks/useSocket";
import type { Report, ServerEvent } from "./types";

const MAX_REPORTS = 500;

const STATUS_STYLE: Record<SocketStatus, string> = {
  open: "bg-emerald-400",
  connecting: "bg-amber-400 animate-pulse",
  closed: "bg-rose-500",
};

export default function App() {
  const [reports, setReports] = useState<Map<string, Report>>(() => new Map());

  const upsert = useCallback((incoming: Report[]) => {
    setReports((prev) => {
      const next = new Map(prev);
      for (const report of incoming) next.set(report.id, report);
      return next;
    });
  }, []);

  const status = useSocket(
    useCallback(
      (event: ServerEvent) => {
        if (event.type === "report.created") upsert([event.data]);
      },
      [upsert],
    ),
  );

  useEffect(() => {
    fetch("/api/reports?limit=100")
      .then((response) => (response.ok ? (response.json() as Promise<Report[]>) : []))
      .then(upsert)
      .catch(() => undefined);
  }, [upsert]);

  const ordered = useMemo(
    () =>
      [...reports.values()].sort((a, b) => b.received_at - a.received_at).slice(0, MAX_REPORTS),
    [reports],
  );

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col px-4 py-6">
      <header className="flex items-center justify-between border-b border-line pb-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            Sanket <span className="text-signal">·</span> triage board
          </h1>
          <p className="text-sm text-mute">Live reports from every channel</p>
        </div>
        <div className="flex items-center gap-2 text-sm text-mute">
          <span className={`size-2.5 rounded-full ${STATUS_STYLE[status]}`} />
          {status === "open" ? "live" : status}
          <span className="ml-3 rounded-md bg-panel px-2 py-0.5 font-mono text-ink">
            {reports.size}
          </span>
        </div>
      </header>
      {ordered.length === 0 ? (
        <p className="mt-16 text-center text-mute">Waiting for reports…</p>
      ) : (
        <ul className="mt-4 flex flex-col gap-3 pb-8">
          {ordered.map((report) => (
            <ReportCard key={report.id} report={report} />
          ))}
        </ul>
      )}
    </div>
  );
}
