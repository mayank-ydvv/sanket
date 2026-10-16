import { describe, expect, it } from "vitest";
import type { Alert, Incident } from "../types";
import { applyEvents, emptyState, escalationExhausted, liveAlertFor, rankIncidents, waitingLabel } from "./store";

const incident = (id: string, severity: number, first_seen: number, extra: Partial<Incident> = {}): Incident => ({
  id,
  title: `Fire · ${id}`,
  department: "fire",
  severity,
  status: "open",
  lat: null,
  lng: null,
  location_text: null,
  location_confirmed: false,
  report_count: 1,
  first_seen,
  last_updated: first_seen,
  linked_hazards: [],
  briefing: null,
  lane: "confirm",
  confidence: 0.8,
  silent_sos: false,
  prank_suspected: false,
  needs_review: false,
  overrides: {},
  ...extra,
});

describe("rankIncidents", () => {
  it("orders by severity, then longest waiting, and hides merged incidents", () => {
    const { state } = applyEvents(emptyState(), [
      { type: "incident.created", data: incident("a", 3, 100) },
      { type: "incident.created", data: incident("b", 5, 300) },
      { type: "incident.created", data: incident("c", 3, 50) },
      { type: "incident.created", data: incident("d", 5, 10, { status: "merged" }) },
    ]);
    expect(rankIncidents(state.incidents).map((i) => i.id)).toEqual(["b", "c", "a"]);
  });
});

describe("applyEvents", () => {
  it("merges diffs into known entities", () => {
    const start = applyEvents(emptyState(), [{ type: "incident.created", data: incident("a", 3, 100) }]).state;
    const { state, missing } = applyEvents(start, [{ type: "incident.updated", data: { id: "a", severity: 5, report_count: 4 } }]);
    expect(state.incidents.get("a")).toMatchObject({ severity: 5, report_count: 4, title: "Fire · a" });
    expect(missing).toEqual([]);
  });

  it("reports diffs for unknown incidents instead of inventing partial ones", () => {
    const { state, missing } = applyEvents(emptyState(), [{ type: "incident.updated", data: { id: "zz", severity: 4 } }]);
    expect(state.incidents.size).toBe(0);
    expect(missing).toEqual(["zz"]);
  });

  it("keeps untouched collections identical so memoised views do not re-sort", () => {
    const start = applyEvents(emptyState(), [{ type: "incident.created", data: incident("a", 3, 100) }]).state;
    const alert: Alert = {
      id: "al", incident_id: "a", department: "fire", channel: "mock", contact: "Station",
      level: 0, sent_at: 1, acknowledged_at: null, escalated_to: null, triggered_by: "auto",
    };
    const { state } = applyEvents(start, [{ type: "alert.sent", data: alert }]);
    expect(state.incidents).toBe(start.incidents);
    expect(liveAlertFor(state.alerts, "a")?.contact).toBe("Station");
    const acked = applyEvents(state, [{ type: "alert.updated", data: { id: "al", acknowledged_at: 5 } }]).state;
    expect(liveAlertFor(acked.alerts, "a")).toBeUndefined();
    const exhausted = applyEvents(state, [{ type: "alert.updated", data: { id: "al", escalated_to: "exhausted" } }]).state;
    expect(escalationExhausted(exhausted.alerts, "a")).toBe(true);
  });
});

describe("waitingLabel", () => {
  it("formats seconds, minutes and hours", () => {
    expect(waitingLabel(100, 145_000)).toBe("45s");
    expect(waitingLabel(100, 230_000)).toBe("2m 10s");
    expect(waitingLabel(0, 3_900_000)).toBe("1h 5m");
  });
});
