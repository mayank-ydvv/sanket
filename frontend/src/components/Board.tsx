import { escalationExhausted, liveAlertFor, waitingLabel } from "../lib/store";
import type { Alert, Incident } from "../types";
import { Badge, DEPT_STYLE, LANE_STYLE, SeverityChip } from "./Badges";

interface BoardProps {
  incidents: Incident[];
  alerts: Map<string, Alert>;
  selectedId: string | null;
  onSelect: (id: string) => void;
  now: number;
}

export function Board({ incidents, alerts, selectedId, onSelect, now }: BoardProps) {
  if (incidents.length === 0) {
    return <p className="p-8 text-center text-sm text-mute">No incidents yet. Reports will appear here as they arrive.</p>;
  }
  return (
    <ol className="divide-y divide-line">
      {incidents.map((incident) => {
        const live = liveAlertFor(alerts, incident.id);
        const exhausted = escalationExhausted(alerts, incident.id);
        const selected = incident.id === selectedId;
        return (
          <li key={incident.id}>
            <button
              type="button"
              onClick={() => onSelect(incident.id)}
              className={`flex w-full gap-3 px-4 py-3 text-left transition-colors hover:bg-white/[0.03] ${selected ? "bg-white/[0.06]" : ""}`}
            >
              <SeverityChip severity={incident.severity} />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <p className="truncate text-sm font-medium">{incident.title}</p>
                  <span className="shrink-0 font-mono text-[11px] text-mute" title="waiting since first report">
                    {waitingLabel(incident.first_seen, now)}
                  </span>
                </div>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  <Badge className={DEPT_STYLE[incident.department]}>{incident.department}</Badge>
                  <Badge className="bg-white/5 text-mute ring-white/10" title="reports merged into this incident">
                    {incident.report_count} report{incident.report_count === 1 ? "" : "s"}
                  </Badge>
                  <Badge className="bg-white/5 text-mute ring-white/10" title="mean decision confidence">
                    {Math.round(incident.confidence * 100)}%
                  </Badge>
                  <Badge className={LANE_STYLE[incident.lane].className}>{LANE_STYLE[incident.lane].label}</Badge>
                  {incident.silent_sos && <Badge className="bg-rose-600/25 text-rose-100 ring-rose-500/50">silent SOS</Badge>}
                  {incident.prank_suspected && <Badge className="bg-white/5 text-mute ring-white/10">prank?</Badge>}
                  {incident.needs_review && !incident.silent_sos && (
                    <Badge className="bg-yellow-400/15 text-yellow-200 ring-yellow-400/30">needs review</Badge>
                  )}
                  {!incident.location_confirmed && (
                    <Badge className="bg-white/5 text-mute ring-white/10">location unconfirmed</Badge>
                  )}
                  {exhausted && (
                    <Badge className="bg-red-600/30 text-red-100 ring-red-500/60" title="every contact was alerted; nobody acknowledged">
                      no ack · ladder exhausted
                    </Badge>
                  )}
                  {incident.status === "dispatched" && !exhausted && (
                    <Badge className={live ? "bg-fuchsia-500/15 text-fuchsia-200 ring-fuchsia-500/30" : "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30"}>
                      {live ? `alerted · ${live.contact}` : "dispatched"}
                    </Badge>
                  )}
                </div>
              </div>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
