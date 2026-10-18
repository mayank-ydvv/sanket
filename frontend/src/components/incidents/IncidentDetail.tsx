import { AlertTriangle, Check, GitMerge, Scissors, Send, X } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useState } from "react";
import { DEPARTMENT_LABEL, DepartmentBadge, LaneBadge, NeutralPill, Pill, SeverityChip } from "@/components/ui/badges";
import { Button } from "@/components/ui/Button";
import { ApiError, api } from "@/lib/api";
import { liveAlertFor } from "@/lib/store";
import { cn } from "@/lib/utils";
import type { Alert, Department, Incident, IncidentDetail as Detail, Report } from "@/types";

const DEPARTMENTS: Department[] = ["fire", "police", "medical", "disaster", "utilities", "none"];
const RULE_LABEL: Record<string, string> = { silent_sos: "Silent SOS", severity_floor: "Life-safety floor", prank_suspected: "Prank?" };
const clock = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });

type Tab = "summary" | "reports" | "activity";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <h3 className="text-[11px] font-semibold uppercase tracking-wider text-mute">{title}</h3>
      {children}
    </section>
  );
}

function ReportRow({ report, canSplit, onSplit }: { report: Report; canSplit: boolean; onSplit: () => void }) {
  const d = report.decision;
  return (
    <li className="rounded-xl border border-line bg-bg p-3.5">
      <div className="flex items-center justify-between gap-2 text-[11px] text-mute">
        <span className="font-mono">
          {clock.format(report.received_at * 1000)} · {report.channel}
          {report.language ? ` · ${report.language}` : ""}
        </span>
        {canSplit && (
          <button type="button" onClick={onSplit} className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-live hover:bg-live-soft">
            <Scissors className="size-3" /> Split out
          </button>
        )}
      </div>
      <p className="mt-2 text-sm leading-relaxed">{report.raw_text || <em className="text-mute">Silent call: no words</em>}</p>
      {d && (
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          <DepartmentBadge department={d.department} />
          <NeutralPill>sev {d.severity}</NeutralPill>
          <NeutralPill title="who decided, and how sure">
            {report.source} · {Math.round((report.confidence ?? 0) * 100)}%
          </NeutralPill>
          {report.refining && <Pill className="animate-pulse bg-live-soft text-live ring-live/30">LLM re-checking…</Pill>}
          {report.flags.map((flag) => (
            <Pill key={flag} className="bg-danger/10 text-danger ring-danger/25">
              {RULE_LABEL[flag.split(":")[0]] ?? flag}
            </Pill>
          ))}
          {d.people_at_risk && <NeutralPill>{d.people_at_risk}</NeutralPill>}
        </div>
      )}
    </li>
  );
}

export function IncidentDetail({
  incident,
  incidents,
  alerts,
  onClose,
  onSelect,
}: {
  incident: Incident;
  incidents: Map<string, Incident>;
  alerts: Map<string, Alert>;
  onClose: () => void;
  onSelect: (id: string) => void;
}) {
  const [tab, setTab] = useState<Tab>("summary");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [department, setDepartment] = useState<Department>(incident.department);
  const [severity, setSeverity] = useState(incident.severity);
  const live = liveAlertFor(alerts, incident.id);
  const base = `/incidents/${incident.id}`;

  const load = useCallback(async () => {
    try {
      setDetail(await api<Detail>(base));
    } catch {
      /* the list still shows the incident; detail retries on the next change */
    }
  }, [base]);

  useEffect(() => {
    void load();
  }, [load, incident.last_updated, incident.report_count, incident.status, incident.severity, live?.id]);

  useEffect(() => {
    setDepartment(incident.department);
    setSeverity(incident.severity);
  }, [incident.id, incident.department, incident.severity]);

  const act = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const reports = detail?.reports ?? [];
  const tabs: { id: Tab; label: string }[] = [
    { id: "summary", label: "Summary" },
    { id: "reports", label: `Reports (${incident.report_count})` },
    { id: "activity", label: "Activity" },
  ];

  return (
    <aside className="flex h-full flex-col overflow-hidden rounded-2xl border border-line bg-surface shadow-2xl">
      <header className="border-b border-line px-5 pb-0 pt-5">
        <div className="flex items-start gap-3">
          <SeverityChip severity={incident.severity} />
          <div className="min-w-0 flex-1">
            <h2 className="font-display text-lg font-semibold leading-tight">{incident.title}</h2>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <DepartmentBadge department={incident.department} />
              <LaneBadge lane={incident.lane} />
              <NeutralPill>{incident.status}</NeutralPill>
              {incident.silent_sos && <Pill className="bg-danger/15 text-danger ring-danger/30">Silent SOS</Pill>}
              {Object.keys(incident.overrides).length > 0 && <NeutralPill>overridden</NeutralPill>}
            </div>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="grid size-8 place-items-center rounded-lg text-mute hover:bg-surface-2 hover:text-ink">
            <X className="size-4" />
          </button>
        </div>
        <div className="mt-4 flex gap-2">
          <Button size="sm" disabled={busy || incident.status === "dispatched"} onClick={() => act(() => api(`${base}/confirm`, { method: "POST" }))}>
            <Send className="size-3.5" /> {incident.status === "dispatched" ? "Dispatched" : "Confirm & dispatch"}
          </Button>
          <Button size="sm" variant="secondary" disabled={busy || !live} onClick={() => act(() => api(`${base}/ack`, { method: "POST" }))}>
            <Check className="size-3.5" /> Acknowledge
          </Button>
        </div>
        <nav className="mt-4 flex gap-5 text-sm" role="tablist">
          {tabs.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                "-mb-px border-b-2 pb-2.5 font-medium transition",
                tab === t.id ? "border-accent text-ink" : "border-transparent text-mute hover:text-ink",
              )}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>

      {error && <p className="mx-5 mt-4 rounded-xl bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p>}

      <div className="flex-1 space-y-6 overflow-y-auto p-5">
        {tab === "summary" && (
          <>
            {incident.combined_risk && (
              <div role="alert" className="flex gap-3 rounded-xl border border-accent/40 bg-accent-soft p-4 text-sm text-accent-ink">
                <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                <p>
                  <span className="font-semibold">Linked risk. </span>
                  {incident.combined_risk}
                </p>
              </div>
            )}
            {incident.briefing && incident.reasoned_at && (
              <Section title="Responder briefing">
                <ol className="space-y-2 rounded-xl border border-line bg-bg p-4 text-sm leading-relaxed">
                  {incident.briefing.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ol>
                <p className="text-[11px] text-mute">System 2 · {clock.format(incident.reasoned_at * 1000)} · drawn from the reports only, check before relaying</p>
              </Section>
            )}
            <Section title="Situation">
              <dl className="grid grid-cols-[120px_1fr] gap-y-2 text-sm">
                <dt className="text-mute">Location</dt>
                <dd>
                  {incident.location_text ?? "—"}
                  {!incident.location_confirmed && <span className="ml-1 text-xs text-warn">(unconfirmed, call back)</span>}
                </dd>
                <dt className="text-mute">Reports</dt>
                <dd>{incident.report_count}</dd>
                <dt className="text-mute">Confidence</dt>
                <dd>{Math.round(incident.confidence * 100)}%</dd>
                <dt className="text-mute">Hazards</dt>
                <dd>{[...new Set([...incident.risk_hazards, ...incident.linked_hazards])].join(", ").replaceAll("_", " ") || "—"}</dd>
              </dl>
            </Section>
            {incident.merge_suggestions.length > 0 && (
              <Section title="Possibly the same event">
                <ul className="space-y-2">
                  {incident.merge_suggestions.map((id) => {
                    const other = incidents.get(id);
                    return (
                      <li key={id} className="flex items-center justify-between gap-3 rounded-xl border border-line bg-bg px-3.5 py-2.5 text-sm">
                        <button type="button" className="truncate text-left text-live hover:underline" onClick={() => onSelect(id)}>
                          {other ? `${other.title} · ${other.report_count} reports` : id}
                        </button>
                        <Button size="sm" variant="secondary" disabled={busy || other?.status === "merged"} onClick={() => act(() => api(`/incidents/${id}/merge`, { body: { into: incident.id } }))}>
                          <GitMerge className="size-3.5" /> Merge here
                        </Button>
                      </li>
                    );
                  })}
                </ul>
              </Section>
            )}
            <Section title="Override">
              <div className="flex flex-wrap gap-2">
                <select value={department} onChange={(e) => setDepartment(e.target.value as Department)} aria-label="Department" className="h-9 rounded-lg border border-line bg-bg px-2.5 text-sm">
                  {DEPARTMENTS.map((d) => (
                    <option key={d} value={d}>
                      {DEPARTMENT_LABEL[d]}
                    </option>
                  ))}
                </select>
                <select value={severity} onChange={(e) => setSeverity(Number(e.target.value))} aria-label="Severity" className="h-9 rounded-lg border border-line bg-bg px-2.5 text-sm">
                  {[1, 2, 3, 4, 5].map((s) => (
                    <option key={s} value={s}>
                      Severity {s}
                    </option>
                  ))}
                </select>
                <Button size="sm" variant="secondary" disabled={busy || (department === incident.department && severity === incident.severity)} onClick={() => act(() => api(`${base}/override`, { body: { department, severity } }))}>
                  Apply
                </Button>
              </div>
            </Section>
          </>
        )}

        {tab === "reports" && (
          <ul className="space-y-2.5">
            {reports.map((report) => (
              <ReportRow
                key={report.id}
                report={report}
                canSplit={reports.length > 1}
                onSplit={() => act(() => api(`${base}/split`, { body: { report_id: report.id } }))}
              />
            ))}
          </ul>
        )}

        {tab === "activity" && detail && (
          <>
            <Section title="Alerts">
              {detail.alerts.length === 0 ? (
                <p className="text-sm text-mute">No alerts sent yet.</p>
              ) : (
                <ul className="space-y-2">
                  {detail.alerts.map((a) => (
                    <li key={a.id} className="flex items-center justify-between gap-3 rounded-xl border border-line bg-bg px-3.5 py-2.5 text-sm">
                      <span>
                        <span className="font-mono text-xs text-mute">L{a.level}</span> {a.contact}
                        <span className="text-xs text-mute"> · {a.triggered_by}</span>
                      </span>
                      <span className="text-xs text-mute">{a.acknowledged_at ? "acknowledged" : a.escalated_to ? `→ ${a.escalated_to}` : "waiting"}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Section>
            <Section title="Audit trail">
              <ol className="relative space-y-3 border-l border-line pl-4">
                {detail.audit.map((entry, i) => (
                  <li key={i} className="text-sm">
                    <span className="absolute -left-[5px] mt-1.5 size-2.5 rounded-full border-2 border-surface bg-line-strong" />
                    <p>
                      <span className="font-medium">{entry.action}</span> <span className="text-mute">by {entry.actor}</span>
                    </p>
                    <p className="font-mono text-[11px] text-mute">{clock.format(entry.at * 1000)}</p>
                  </li>
                ))}
              </ol>
            </Section>
          </>
        )}
      </div>
    </aside>
  );
}
