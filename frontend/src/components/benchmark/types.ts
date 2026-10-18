export interface ApproachResult {
  approach: string;
  triage_acc: number;
  triage_acc_hidden50: number;
  emergency: { precision: number; recall: number; f1: number };
  department_acc: number;
  severity_mae: number;
  silent_sos_caught: string;
  unanswered: number;
  latency_ms: { median: number; p95: number };
  llm_calls: number;
  cost_per_1000_inr: number;
  per_language: Record<string, { triage_acc: number }>;
  notes: string[];
}

export interface Benchmark {
  run_at: string;
  n: number;
  reports_per_second: number;
  approaches: ApproachResult[];
  local_gate_curve?: { gate: number; coverage: number; triage_acc_on_covered: number }[];
  notes: string[];
}

export const HYBRID = "Sanket hybrid";

export function latencyLabel(ms: number): string {
  if (ms < 1) return "<1 ms";
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}
