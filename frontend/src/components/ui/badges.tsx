import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { Department, Lane } from "@/types";

const DEPT: Record<Department, { label: string; className: string }> = {
  fire: { label: "Fire", className: "bg-orange-500/10 text-orange-700 ring-orange-500/25 dark:text-orange-300" },
  police: { label: "Police", className: "bg-blue-500/10 text-blue-700 ring-blue-500/25 dark:text-blue-300" },
  medical: { label: "Medical", className: "bg-rose-500/10 text-rose-700 ring-rose-500/25 dark:text-rose-300" },
  disaster: { label: "Disaster", className: "bg-violet-500/10 text-violet-700 ring-violet-500/25 dark:text-violet-300" },
  utilities: { label: "Utilities", className: "bg-amber-500/10 text-amber-800 ring-amber-500/30 dark:text-amber-300" },
  none: { label: "Unclassified", className: "bg-slate-500/10 text-slate-600 ring-slate-500/25 dark:text-slate-300" },
};

const LANE: Record<Lane, { label: string; className: string }> = {
  auto: { label: "Auto-dispatch", className: "bg-emerald-500/10 text-emerald-700 ring-emerald-500/25 dark:text-emerald-300" },
  confirm: { label: "Confirm", className: "bg-sky-500/10 text-sky-700 ring-sky-500/25 dark:text-sky-300" },
  review: { label: "Human review", className: "bg-yellow-500/15 text-yellow-800 ring-yellow-500/30 dark:text-yellow-200" },
};

export function Pill({ className, children, title }: { className?: string; children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-md px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset",
        className,
      )}
    >
      {children}
    </span>
  );
}

export function DepartmentBadge({ department }: { department: Department }) {
  return <Pill className={DEPT[department].className}>{DEPT[department].label}</Pill>;
}

export function LaneBadge({ lane }: { lane: Lane }) {
  return <Pill className={LANE[lane].className}>{LANE[lane].label}</Pill>;
}

export function NeutralPill({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <Pill title={title} className="bg-surface-2 text-ink-2 ring-line">
      {children}
    </Pill>
  );
}

export function severityColor(severity: number): string {
  return `var(--sev-${Math.min(5, Math.max(1, severity))})`;
}

export function SeverityDot({ severity }: { severity: number }) {
  return <span className="inline-block size-2 rounded-full" style={{ backgroundColor: severityColor(severity) }} />;
}

export function SeverityChip({ severity, size = "md" }: { severity: number; size?: "sm" | "md" }) {
  return (
    <span
      title={`Severity ${severity} of 5`}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-lg font-mono font-bold text-white",
        size === "md" ? "size-9 text-sm" : "size-7 text-xs",
      )}
      style={{ backgroundColor: severityColor(severity) }}
    >
      {severity}
    </span>
  );
}

export const DEPARTMENT_LABEL = Object.fromEntries(Object.entries(DEPT).map(([k, v]) => [k, v.label])) as Record<
  Department,
  string
>;
