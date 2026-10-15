export type Department = "fire" | "police" | "medical" | "disaster" | "utilities" | "none";
export type Channel = "call" | "sms" | "web" | "whatsapp";
export type DecisionSource = "local" | "llm" | "rules";

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
}

export type ServerEvent = { type: "report.created"; data: Report };
