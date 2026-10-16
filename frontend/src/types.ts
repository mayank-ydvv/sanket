export type Department = "fire" | "police" | "medical" | "disaster" | "utilities" | "none";
export type Channel = "call" | "sms" | "web" | "whatsapp";
export type DecisionSource = "local" | "llm" | "rules";
export type Lane = "auto" | "confirm" | "review";
export type IncidentStatus = "open" | "dispatched" | "resolved" | "merged";

export interface Decision {
  is_emergency: boolean;
  emergency_prob: number;
  department: Department;
  department_conf: number;
  severity: number;
  alert_now: boolean;
  location_text: string | null;
  people_at_risk: string | null;
  hazards: string[];
  silent_sos: boolean;
  prank_score: number;
  needs_human_review: boolean;
}

export interface Report {
  id: string;
  channel: Channel;
  caller_hash: string | null;
  raw_text: string;
  received_at: number;
  language: string | null;
  english_gloss: string | null;
  decision: Decision | null;
  confidence: number | null;
  incident_id: string | null;
  flags: string[];
  source: DecisionSource | null;
  location_text: string | null;
  lat: number | null;
  lng: number | null;
  refining: boolean;
  lane: Lane | null;
}

export interface Incident {
  id: string;
  title: string;
  department: Department;
  severity: number;
  status: IncidentStatus;
  lat: number | null;
  lng: number | null;
  location_text: string | null;
  location_confirmed: boolean;
  report_count: number;
  first_seen: number;
  last_updated: number;
  linked_hazards: string[];
  briefing: string[] | null;
  lane: Lane;
  confidence: number;
  silent_sos: boolean;
  prank_suspected: boolean;
  needs_review: boolean;
  overrides: Record<string, string | number>;
}

export interface Alert {
  id: string;
  incident_id: string;
  department: Department;
  channel: string;
  contact: string;
  level: number;
  sent_at: number;
  acknowledged_at: number | null;
  escalated_to: string | null;
  triggered_by: string;
}

export interface AuditEntry {
  action: string;
  actor: string;
  before: string | null;
  after: string | null;
  at: number;
}

export interface IncidentDetail {
  incident: Incident;
  reports: Report[];
  audit: AuditEntry[];
  alerts: Alert[];
}

/** Created events carry the full entity; updated events carry `id` + changed fields only. */
export type LiveEvent =
  | { type: "incident.created"; data: Incident }
  | { type: "incident.updated"; data: Partial<Incident> & { id: string } }
  | { type: "report.created"; data: Report }
  | { type: "report.updated"; data: Partial<Report> & { id: string } }
  | { type: "alert.sent"; data: Alert }
  | { type: "alert.updated"; data: Partial<Alert> & { id: string } };

export type ServerMessage = { type: "batch"; data: LiveEvent[] };
