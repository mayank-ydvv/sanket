import { type ReactNode, useCallback, useEffect, useState } from "react";
import { liveAlertFor } from "../lib/store";
import type { Alert, Department, Incident, IncidentDetail as Detail, Report } from "../types";
import { Badge, DEPT_STYLE, LANE_STYLE, RULE_LABEL, SeverityChip } from "./Badges";

const DEPARTMENTS: Department[] = ["fire", "police", "medical", "disaster", "utilities", "none"];
const clock = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });

async function post<T>(url: string, body?: unknown): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: body ? { "content-type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? response.statusText);
  return (await response.json()) as T;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-t border-line px-5 py-4">
      <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-mute">{title}</h3>
      {children}
    </section>
  );
}

function ReportItem({ report, onSplit, canSplit }: { report: Report; onSplit: () => void; canSplit: boolean }) {
  const d = report.decision;
  return (
    <li className="rounded-lg border border-line bg-black/20 p-3">
      <div className="flex items-center justify-between gap-2 text-[11px] text-mute">
        <span className="font-mono">
          {clock.format(report.received_at * 1000)} · {report.channel}
          {report.language ? ` · ${report.language}` : ""}
          {report.language ? ` · ${report.language}` : ""}
        </span>
        {canSplit && (
          <button type="button" onClick={onSplit} className="rounded px-1.5 py-0.5 text-sky-300 hover:bg-sky-500/10">
            split out
          </button>
        )}
      </div>
      <p className="mt-1.5 text-sm leading-relaxed break-words">{report.raw_text || <em className="text-mute">(empty)</em>}</p>
      {report.english_gloss && <p className="mt-1 text-xs text-mute italic">“{report.english_gloss}”</p>}
      {d && (
        <div className="mt-2 flex flex-wrap gap-1">
          <Badge className={DEPT_STYLE[d.department]}>{d.department}</Badge>
          <Badge className="bg-white/5 text-ink ring-white/10">sev {d.severity}</Badge>
          <Badge className="bg-white/5 text-mute ring-white/10" title="decision source and confidence">
            {report.source} · {Math.round((report.confidence ?? 0) * 100)}%
          </Badge>
          {report.refining && <Badge className="animate-pulse bg-indigo-500/15 text-indigo-200 ring-indigo-500/30">LLM re-checking…</Badge>}
          {report.flags.map((flag) => (
            <Badge key={flag} className="bg-rose-500/15 text-rose-200 ring-rose-500/30" title={flag}>
              {RULE_LABEL[flag.split(":")[0]] ?? flag}
            </Badge>
          ))}
          {d.people_at_risk && <Badge className="bg-white/5 text-ink ring-white/10">{d.people_at_risk}</Badge>}
        </div>
      )}
    </li>
  );
}

interface Props {
  incident: Incident;
  incidents: Map<string, Incident>;
  alerts: Map<string, Alert>;
  onClose: () => void;
  onSelect: (id: string) => void;
}

export function IncidentDetail({ incident, incidents, alerts, onClose, onSelect }: Props) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [department, setDepartment] = useState<Department>(incident.department);
  const [severity, setSeverity] = useState(incident.severity);
  const live = liveAlertFor(alerts, incident.id);

  const load = useCallback(async () => {
    const response = await fetch(`/api/incidents/${incident.id}`);
    if (response.ok) setDetail((await response.json()) as Detail);
  }, [incident.id]);

  // Refetch when the live incident changes (new reports, revisions, alerts).
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
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const base = `/api/incidents/${incident.id}`;
  const reports = detail?.reports ?? [];

  return (
    <aside className="flex h-full flex-col overflow-hidden bg-panel shadow-2xl ring-1 ring-line">
      <header className="flex items-start gap-3 px-5 py-4">
        <SeverityChip severity={incident.severity} />
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-semibold leading-tight">{incident.title}</h2>
          <div className="mt-1.5 flex flex-wrap gap-1">
            <Badge className={DEPT_STYLE[incident.department]}>{incident.department}</Badge>
            <Badge className={LANE_STYLE[incident.lane].className}>{LANE_STYLE[incident.lane].label}</Badge>
            <Badge className="bg-white/5 text-mute ring-white/10">{incident.status}</Badge>
            {incident.silent_sos && <Badge className="bg-rose-600/25 text-rose-100 ring-rose-500/50">silent SOS</Badge>}
            {Object.keys(incident.overrides).length > 0 && (
              <Badge className="bg-white/5 text-mute ring-white/10">overridden</Badge>
            )}
          </div>
        </div>
        <button type="button" onClick={onClose} aria-label="Close" className="rounded-md px-2 py-1 text-mute hover:bg-white/5 hover:text-ink">
          ✕
        </button>
      </header>

      <div className="flex flex-wrap gap-2 px-5 pb-4">
        <button
          type="button"
          disabled={busy || incident.status === "dispatched"}
          onClick={() => act(() => post(`${base}/confirm`))}
          className="rounded-lg bg-signal px-3 py-1.5 text-sm font-semibold text-black disabled:opacity-40"
        >
          {incident.status === "dispatched" ? "Dispatched" : "Confirm & dispatch"}
        </button>
        <button
          type="button"
          disabled={busy || !live}
          onClick={() => act(() => post(`${base}/ack`))}
          className="rounded-lg bg-white/10 px-3 py-1.5 text-sm font-medium disabled:opacity-40"
        >
          Acknowledge
        </button>
      </div>
      {error && <p className="mx-5 mb-3 rounded-md bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{error}</p>}

      <div className="flex-1 overflow-y-auto">
        {incident.combined_risk && (
          <div className="mx-5 mb-3 rounded-lg border border-amber-400/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-100" role="alert">
            <span className="font-semibold">⚠ Linked risk:</span> {incident.combined_risk}
          </div>
        )}
        {incident.briefing && incident.reasoned_at && (
          <Section title="Responder briefing">
            <ol className="space-y-1 text-sm">
              {incident.briefing.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ol>
            <p className="mt-2 text-[11px] text-mute">
              System 2 · {clock.format(incident.reasoned_at * 1000)} · from the reports only, check before relaying
            </p>
          </Section>
        )}
        {incident.merge_suggestions.length > 0 && (
          <Section title="Possibly the same event">
            <ul className="space-y-2">
              {incident.merge_suggestions.map((id) => {
                const other = incidents.get(id);
                return (
                  <li key={id} className="flex items-center justify-between gap-2 text-sm">
                    <button type="button" className="truncate text-left text-sky-300 hover:underline" onClick={() => onSelect(id)}>
                      {other ? `${other.title} · ${other.report_count} reports` : id}
                    </button>
                    <button
                      type="button"
                      disabled={busy || other?.status === "merged"}
                      onClick={() => act(() => post(`/api/incidents/${id}/merge`, { into: incident.id }))}
                      className="shrink-0 rounded-lg bg-white/10 px-2.5 py-1 text-xs font-medium disabled:opacity-40"
                      title="Move that incident's reports into this one"
                    >
                      Merge here
                    </button>
                  </li>
                );
              })}
            </ul>
          </Section>
        )}
        <Section title="Situation">
          <dl className="grid grid-cols-[110px_1fr] gap-y-1 text-sm">
            <dt className="text-mute">Location</dt>
            <dd>
              {incident.location_text ?? "—"} {!incident.location_confirmed && <span className="text-xs text-yellow-200">(unconfirmed — call back)</span>}
            </dd>
            <dt className="text-mute">Reports</dt>
            <dd>{incident.report_count}</dd>
            <dt className="text-mute">Confidence</dt>
            <dd>{Math.round(incident.confidence * 100)}%</dd>
            <dt className="text-mute">Hazards</dt>
            <dd>
              {[...new Set([...incident.risk_hazards, ...incident.linked_hazards])].join(", ").replaceAll("_", " ") || "—"}
            </dd>
          </dl>
          {incident.briefing && !incident.reasoned_at && (
            <p className="mt-3 text-sm text-mute">{incident.briefing.join(" ")}</p>
          )}
        </Section>

        <Section title="Override">
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={department}
              onChange={(e) => setDepartment(e.target.value as Department)}
              className="rounded-md border border-line bg-bg px-2 py-1 text-sm"
              aria-label="Department"
            >
              {DEPARTMENTS.map((d) => (
                <option key={d}>{d}</option>
              ))}
            </select>
            <select
              value={severity}
              onChange={(e) => setSeverity(Number(e.target.value))}
              className="rounded-md border border-line bg-bg px-2 py-1 text-sm"
              aria-label="Severity"
            >
              {[1, 2, 3, 4, 5].map((s) => (
                <option key={s} value={s}>
                  severity {s}
                </option>
              ))}
            </select>
            <button
              type="button"
              disabled={busy || (department === incident.department && severity === incident.severity)}
              onClick={() => act(() => post(`${base}/override`, { department, severity }))}
              className="rounded-lg bg-white/10 px-3 py-1.5 text-sm font-medium disabled:opacity-40"
            >
              Override
            </button>
          </div>
        </Section>

        {detail && detail.alerts.length > 0 && (
          <Section title="Alerts">
            <ul className="space-y-1 text-sm">
              {detail.alerts.map((a) => (
                <li key={a.id} className="flex justify-between gap-2">
                  <span>
                    L{a.level} · {a.contact} <span className="text-mute">({a.triggered_by}, {a.channel})</span>
                  </span>
                  <span className="shrink-0 font-mono text-xs text-mute">
                    {a.acknowledged_at ? "ack'd" : a.escalated_to ? `→ ${a.escalated_to}` : "waiting"}
                  </span>
                </li>
              ))}
            </ul>
          </Section>
        )}

        <Section title={`Merged reports (${reports.length})`}>
          <ul className="space-y-2">
            {reports.map((report) => (
              <ReportItem
                key={report.id}
                report={report}
                canSplit={reports.length > 1}
                onSplit={() => act(() => post(`${base}/split`, { report_id: report.id }))}
              />
            ))}
          </ul>
        </Section>

        {detail && (
          <Section title="Audit trail">
            <ol className="space-y-1 font-mono text-[11px] text-mute">
              {detail.audit.map((entry, i) => (
                <li key={i}>
                  {clock.format(entry.at * 1000)} · <span className="text-ink">{entry.action}</span> by {entry.actor}
                  {entry.after && <span className="block truncate pl-4 opacity-70">{entry.after}</span>}
                </li>
              ))}
            </ol>
          </Section>
        )}
      </div>
    </aside>
  );
}
