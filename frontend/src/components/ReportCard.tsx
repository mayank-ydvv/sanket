import type { ReactNode } from "react";
import type { Department, Report } from "../types";

const DEPT_STYLE: Record<Department, string> = {
  fire: "bg-orange-500/15 text-orange-300 ring-orange-500/30",
  police: "bg-blue-500/15 text-blue-300 ring-blue-500/30",
  medical: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  disaster: "bg-violet-500/15 text-violet-300 ring-violet-500/30",
  utilities: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  none: "bg-slate-500/15 text-slate-300 ring-slate-500/30",
};

const timeFormat = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

function Badge({ className, children }: { className: string; children: ReactNode }) {
  return (
    <span className={`rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${className}`}>
      {children}
    </span>
  );
}

export function ReportCard({ report }: { report: Report }) {
  const { decision } = report;
  return (
    <li className="rounded-xl border border-line bg-panel p-4">
      <div className="flex flex-wrap items-center gap-2 text-xs text-mute">
        <span className="font-mono">{timeFormat.format(report.received_at * 1000)}</span>
        <span className="uppercase tracking-wide">{report.channel}</span>
        <span className="font-mono opacity-60">{report.id.slice(0, 10)}</span>
      </div>
      <p className="mt-2 text-[15px] leading-relaxed break-words">
        {report.raw_text || <em className="text-mute">(empty report)</em>}
      </p>
      {decision && (
        <div className="mt-3 flex flex-wrap gap-2">
          <Badge className={DEPT_STYLE[decision.department]}>{decision.department}</Badge>
          <Badge className="bg-white/5 text-ink ring-white/10">severity {decision.severity}</Badge>
          {report.confidence !== null && (
            <Badge className="bg-white/5 text-mute ring-white/10">
              {Math.round(report.confidence * 100)}% · {report.source}
            </Badge>
          )}
          {decision.needs_human_review && (
            <Badge className="bg-yellow-400/15 text-yellow-200 ring-yellow-400/30">needs review</Badge>
          )}
        </div>
      )}
    </li>
  );
}
