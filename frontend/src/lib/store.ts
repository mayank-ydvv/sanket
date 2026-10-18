import type { Translate } from "@/lib/i18n";
import type { Alert, CostSnapshot, Incident, LiveEvent, Report, SimulationStatus } from "../types";

export interface LiveState {
  incidents: Map<string, Incident>;
  reports: Map<string, Report>;
  alerts: Map<string, Alert>;
  cost: CostSnapshot | null;
  simulation: SimulationStatus | null;
}

export const MAX_REPORTS = 2000;

export function emptyState(): LiveState {
  return { incidents: new Map(), reports: new Map(), alerts: new Map(), cost: null, simulation: null };
}

/** Board order: most severe first, then whoever has waited longest. */
export function compareIncidents(a: Incident, b: Incident): number {
  return b.severity - a.severity || a.first_seen - b.first_seen || a.id.localeCompare(b.id);
}

export function rankIncidents(incidents: Map<string, Incident>): Incident[] {
  return [...incidents.values()].filter((i) => i.status !== "merged").sort(compareIncidents);
}

function upsert<T extends { id: string }>(
  map: Map<string, T>,
  data: Partial<T> & { id: string },
  full: boolean,
): boolean {
  const current = map.get(data.id);
  if (!full && current === undefined) return false; // diff for an entity we never saw
  map.set(data.id, { ...(current ?? {}), ...data } as T);
  return true;
}

/**
 * Apply one batch of server events. Only the maps an event touches are copied,
 * so unchanged collections keep their identity and their memoised views.
 * Returns the ids of incidents that arrived as diffs we could not apply
 * (the caller fetches those in full).
 */
export function applyEvents(state: LiveState, events: LiveEvent[]): { state: LiveState; missing: string[] } {
  let incidents = state.incidents;
  let reports = state.reports;
  let alerts = state.alerts;
  let { cost, simulation } = state;
  const missing: string[] = [];
  for (const event of events) {
    const [entity, kind] = event.type.split(".") as [string, string];
    const full = kind === "created" || kind === "sent";
    if (entity === "incident") {
      if (incidents === state.incidents) incidents = new Map(incidents);
      if (!upsert(incidents, event.data as Partial<Incident> & { id: string }, full)) missing.push(event.data.id);
    } else if (entity === "report") {
      if (reports === state.reports) reports = new Map(reports);
      upsert(reports, event.data as Partial<Report> & { id: string }, full);
    } else if (entity === "alert") {
      if (alerts === state.alerts) alerts = new Map(alerts);
      upsert(alerts, event.data as Partial<Alert> & { id: string }, full);
    } else if (entity === "cost") {
      cost = { ...(cost ?? {}), ...event.data } as CostSnapshot;
    } else if (entity === "simulation") {
      simulation = { ...(simulation ?? {}), ...event.data } as SimulationStatus;
    }
  }
  if (reports !== state.reports && reports.size > MAX_REPORTS) {
    const oldest = [...reports.values()].sort((a, b) => a.received_at - b.received_at);
    for (const report of oldest.slice(0, reports.size - MAX_REPORTS)) reports.delete(report.id);
  }
  return { state: { incidents, reports, alerts, cost, simulation }, missing };
}

export function latestAlertFor(alerts: Map<string, Alert>, incidentId: string): Alert | undefined {
  let latest: Alert | undefined;
  for (const alert of alerts.values()) {
    if (alert.incident_id !== incidentId) continue;
    if (!latest || alert.sent_at > latest.sent_at) latest = alert;
  }
  return latest;
}

/** The alert still waiting for an acknowledgement, if any. */
export function liveAlertFor(alerts: Map<string, Alert>, incidentId: string): Alert | undefined {
  const latest = latestAlertFor(alerts, incidentId);
  return latest && !latest.acknowledged_at && !latest.escalated_to ? latest : undefined;
}

/** Every rung of the escalation ladder was alerted and nobody acknowledged. */
export function escalationExhausted(alerts: Map<string, Alert>, incidentId: string): boolean {
  return latestAlertFor(alerts, incidentId)?.escalated_to === "exhausted";
}

export function waitingLabel(firstSeen: number, now: number): string {
  const seconds = Math.max(0, Math.round(now / 1000 - firstSeen));
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 });

export function formatInr(value: number): string {
  if (value > 0 && value < 0.01) return "<₹0.01";
  return inr.format(value);
}

/** "Fire · Anna Nagar 2nd Avenue" in the UI language (the server's title is English). */
export function incidentTitle(incident: Pick<Incident, "department" | "location_text">, t: Translate): string {
  return `${t(`dept.${incident.department}`)} · ${incident.location_text ?? t("location.unconfirmed")}`;
}

export function reportCount(n: number, t: Translate): string {
  return n === 1 ? t("reports.one") : t("reports.count", { n });
}
