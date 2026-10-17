import { useState } from "react";
import type { SimulationStatus } from "../types";

const RUN = { n: 500, seconds: 10, scenario: "flood" };

export function DisasterButton({ simulation }: { simulation: SimulationStatus | null }) {
  const [error, setError] = useState<string | null>(null);
  const running = simulation?.running ?? false;

  const start = async () => {
    setError(null);
    const params = new URLSearchParams({ n: String(RUN.n), seconds: String(RUN.seconds), scenario: RUN.scenario });
    const response = await fetch(`/api/simulate/disaster?${params}`, { method: "POST" });
    if (!response.ok) setError(response.status === 409 ? "already running" : `failed (${response.status})`);
  };

  const pct = simulation && simulation.total ? Math.round((100 * simulation.decided) / simulation.total) : 0;
  return (
    <div className="flex items-center gap-3">
      <button
        type="button"
        onClick={start}
        disabled={running}
        className="rounded-lg bg-rose-600 px-3 py-1.5 text-sm font-semibold text-white shadow shadow-rose-900/40 hover:bg-rose-500 disabled:opacity-50"
        title={`Stream ${RUN.n} simulated ${RUN.scenario} reports in ${RUN.seconds} s through the real pipeline`}
      >
        {running ? "Disaster mode running…" : "Disaster mode"}
      </button>
      {simulation?.total ? (
        <div className="min-w-[150px] text-xs text-mute" aria-live="polite">
          <div className="h-1.5 overflow-hidden rounded bg-white/10">
            <div className="h-full bg-rose-500 transition-[width]" style={{ width: `${pct}%` }} />
          </div>
          <p className="mt-1 font-mono">
            {simulation.decided}/{simulation.total} triaged
            {simulation.decided_s != null && ` in ${simulation.decided_s.toFixed(1)}s`}
          </p>
        </div>
      ) : null}
      {error && <span className="text-xs text-rose-300">{error}</span>}
    </div>
  );
}
