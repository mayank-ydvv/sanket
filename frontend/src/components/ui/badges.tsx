import type { ReactNode } from "react";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import type { Department, Lane } from "@/types";

const DEPT_CLASS: Record<Department, string> = {
  fire: "bg-orange-500/10 text-orange-700 ring-orange-500/25 dark:text-orange-300",
  police: "bg-blue-500/10 text-blue-700 ring-blue-500/25 dark:text-blue-300",
  medical: "bg-rose-500/10 text-rose-700 ring-rose-500/25 dark:text-rose-300",
  disaster: "bg-violet-500/10 text-violet-700 ring-violet-500/25 dark:text-violet-300",
  utilities: "bg-amber-500/10 text-amber-800 ring-amber-500/30 dark:text-amber-300",
  none: "bg-slate-500/10 text-slate-600 ring-slate-500/25 dark:text-slate-300",
};

const LANE_CLASS: Record<Lane, string> = {
  auto: "bg-emerald-500/10 text-emerald-700 ring-emerald-500/25 dark:text-emerald-300",
  confirm: "bg-sky-500/10 text-sky-700 ring-sky-500/25 dark:text-sky-300",
  review: "bg-yellow-500/15 text-yellow-800 ring-yellow-500/30 dark:text-yellow-200",
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
  const { t } = useI18n();
  return <Pill className={DEPT_CLASS[department]}>{t(`dept.${department}`)}</Pill>;
}

export function LaneBadge({ lane }: { lane: Lane }) {
  const { t } = useI18n();
  return <Pill className={LANE_CLASS[lane]}>{t(`lane.${lane}`)}</Pill>;
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
  const { t } = useI18n();
  return (
    <span
      title={t("severity.of5", { n: severity })}
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
