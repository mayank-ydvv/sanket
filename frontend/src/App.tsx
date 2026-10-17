import { useMemo, useState } from "react";
import { Board } from "./components/Board";
import { CostTicker } from "./components/CostTicker";
import { DisasterButton } from "./components/DisasterMode";
import { IncidentDetail } from "./components/IncidentDetail";
import { MapView } from "./components/MapView";
import { useLiveState } from "./hooks/useLiveState";
import { useNow } from "./hooks/useNow";
import type { SocketStatus } from "./hooks/useSocket";
import { liveAlertFor, rankIncidents } from "./lib/store";

const STATUS_STYLE: Record<SocketStatus, string> = {
  open: "bg-emerald-400",
  connecting: "bg-amber-400 animate-pulse",
  closed: "bg-rose-500",
};

function Stat({ label, value, tone = "text-ink" }: { label: string; value: number; tone?: string }) {
  return (
    <div className="flex flex-col items-end leading-tight">
      <span className={`font-mono text-lg font-semibold ${tone}`}>{value}</span>
      <span className="text-[10px] uppercase tracking-wider text-mute">{label}</span>
    </div>
  );
}

export default function App() {
  const { state, status } = useLiveState();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const now = useNow();

  // Re-sort only when the incidents map itself changed.
  const ranked = useMemo(() => rankIncidents(state.incidents), [state.incidents]);
  const selected = selectedId ? state.incidents.get(selectedId) : undefined;
  const stats = useMemo(
    () => ({
      open: ranked.filter((i) => i.status === "open").length,
      review: ranked.filter((i) => i.lane === "review" && i.status === "open").length,
      alerting: ranked.filter((i) => liveAlertFor(state.alerts, i.id)).length,
    }),
    [ranked, state.alerts],
  );

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
        <div className="flex items-center gap-3">
          <div>
            <h1 className="text-lg font-semibold tracking-tight">
              Sanket <span className="text-signal">·</span> control room
            </h1>
            <p className="flex items-center gap-1.5 text-xs text-mute">
              <span className={`size-2 rounded-full ${STATUS_STYLE[status]}`} />
              {status === "open" ? "live" : status} · Noida demo district
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <DisasterButton simulation={state.simulation} />
          <CostTicker cost={state.cost} />
        </div>
        <div className="flex items-center gap-5">
          <Stat label="open" value={stats.open} />
          <Stat label="review" value={stats.review} tone="text-yellow-200" />
          <Stat label="alerting" value={stats.alerting} tone="text-fuchsia-200" />
          <Stat label="reports" value={state.reports.size} tone="text-mute" />
        </div>
      </header>

      <main className="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)_minmax(0,1fr)] lg:grid-cols-[minmax(360px,440px)_1fr] lg:grid-rows-1">
        <section className="min-h-0 overflow-y-auto border-line lg:border-r" aria-label="Ranked incidents">
          <Board incidents={ranked} alerts={state.alerts} selectedId={selectedId} onSelect={setSelectedId} now={now} />
        </section>
        <section className="relative min-h-0" aria-label="Map">
          <MapView incidents={ranked} selectedId={selectedId} onSelect={setSelectedId} />
          {selected && (
            <div className="absolute inset-0 z-[1000] sm:inset-y-3 sm:right-3 sm:left-auto sm:w-[460px]">
              <IncidentDetail key={selected.id} incident={selected} alerts={state.alerts} onClose={() => setSelectedId(null)} />
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
