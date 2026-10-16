import type { ReactNode } from "react";
import type { Department, Lane } from "../types";

export const DEPT_STYLE: Record<Department, string> = {
  fire: "bg-orange-500/15 text-orange-300 ring-orange-500/30",
  police: "bg-blue-500/15 text-blue-300 ring-blue-500/30",
  medical: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  disaster: "bg-violet-500/15 text-violet-300 ring-violet-500/30",
  utilities: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  none: "bg-slate-500/15 text-slate-300 ring-slate-500/30",
};

export const SEVERITY_COLOR: Record<number, string> = {
  5: "#ef4444",
  4: "#f97316",
  3: "#eab308",
  2: "#38bdf8",
  1: "#64748b",
};

export const LANE_STYLE: Record<Lane, { label: string; className: string }> = {
  auto: { label: "auto-dispatch", className: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30" },
  confirm: { label: "confirm", className: "bg-sky-500/15 text-sky-300 ring-sky-500/30" },
  review: { label: "human review", className: "bg-yellow-400/15 text-yellow-200 ring-yellow-400/30" },
};

export const RULE_LABEL: Record<string, string> = {
  silent_sos: "silent SOS",
  severity_floor: "life-safety floor",
  prank_suspected: "prank?",
};

export function Badge({ className, children, title }: { className: string; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center rounded-md px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset ${className}`}>
      {children}
    </span>
  );
}

export function SeverityChip({ severity }: { severity: number }) {
  return (
    <span
      className="inline-flex size-8 shrink-0 items-center justify-center rounded-lg font-mono text-sm font-bold text-black"
      style={{ backgroundColor: SEVERITY_COLOR[severity] ?? SEVERITY_COLOR[1] }}
      title={`severity ${severity} of 5`}
    >
      {severity}
    </span>
  );
}
