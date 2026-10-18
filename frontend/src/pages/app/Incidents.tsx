import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { IncidentDetail } from "@/components/incidents/IncidentDetail";
import { MapView } from "@/components/incidents/MapView";
import { DepartmentBadge, LaneBadge, Pill, SeverityChip } from "@/components/ui/badges";
import { useNow } from "@/hooks/useNow";
import { useI18n } from "@/lib/i18n";
import { useLive } from "@/lib/live";
import type { MessageKey } from "@/lib/messages";
import { escalationExhausted, incidentTitle, liveAlertFor, rankIncidents, reportCount, waitingLabel } from "@/lib/store";
import { cn } from "@/lib/utils";
import type { Incident } from "@/types";

type Filter = "all" | "review" | "dispatched" | "risk";

const FILTERS: { id: Filter; label: MessageKey; test: (i: Incident) => boolean }[] = [
  { id: "all", label: "filter.all", test: () => true },
  { id: "review", label: "filter.review", test: (i) => i.lane === "review" && i.status === "open" },
  { id: "dispatched", label: "filter.dispatched", test: (i) => i.status === "dispatched" },
  { id: "risk", label: "filter.risk", test: (i) => Boolean(i.combined_risk) },
];

export default function Incidents() {
  const { t } = useI18n();
  const { state } = useLive();
  const now = useNow();
  const [params, setParams] = useSearchParams();
  const selectedId = params.get("focus");
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");

  const ranked = useMemo(() => rankIncidents(state.incidents), [state.incidents]);
  const visible = useMemo(() => {
    const test = FILTERS.find((f) => f.id === filter)!.test;
    const q = query.trim().toLowerCase();
    // Matches the English title and the one shown in the UI language.
    return ranked.filter(
      (i) => test(i) && (!q || i.title.toLowerCase().includes(q) || incidentTitle(i, t).toLowerCase().includes(q)),
    );
  }, [ranked, filter, query, t]);
  const selected = selectedId ? state.incidents.get(selectedId) : undefined;
  const select = (id: string | null) => setParams(id ? { focus: id } : {}, { replace: true });

  return (
    <div className="grid h-full min-h-[600px] lg:grid-cols-[400px_1fr]">
      <section className="flex min-h-0 flex-col border-line bg-surface lg:border-r" aria-label={t("incidents.ranked")}>
        <div className="space-y-3 border-b border-line p-4">
          <label className="relative block">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-mute" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("incidents.search")}
              className="h-10 w-full rounded-xl border border-line bg-bg pl-9 pr-3 text-sm outline-none transition focus:border-accent focus:ring-4 focus:ring-accent/15"
            />
          </label>
          <div className="flex gap-1.5 overflow-x-auto">
            {FILTERS.map((f) => {
              const count = ranked.filter(f.test).length;
              return (
                <button
                  key={f.id}
                  type="button"
                  onClick={() => setFilter(f.id)}
                  className={cn(
                    "shrink-0 rounded-lg px-2.5 py-1.5 text-xs font-medium transition",
                    filter === f.id ? "bg-ink text-bg" : "bg-surface-2 text-ink-2 hover:text-ink",
                  )}
                >
                  {t(f.label)} <span className="opacity-60">{count}</span>
                </button>
              );
            })}
          </div>
        </div>
        <ol className="min-h-0 flex-1 divide-y divide-line overflow-y-auto">
          {visible.length === 0 && <p className="p-10 text-center text-sm text-mute">{t("incidents.empty")}</p>}
          {visible.map((incident) => {
            const live = liveAlertFor(state.alerts, incident.id);
            const exhausted = escalationExhausted(state.alerts, incident.id);
            return (
              <li key={incident.id}>
                <button
                  type="button"
                  onClick={() => select(incident.id)}
                  className={cn(
                    "flex w-full gap-3 px-4 py-3.5 text-left transition hover:bg-surface-2",
                    incident.id === selectedId && "bg-accent-soft/60 hover:bg-accent-soft/60",
                  )}
                >
                  <SeverityChip severity={incident.severity} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline justify-between gap-2">
                      <p className="truncate text-sm font-semibold">{incidentTitle(incident, t)}</p>
                      <span className="shrink-0 font-mono text-[11px] text-mute">{waitingLabel(incident.first_seen, now)}</span>
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                      <DepartmentBadge department={incident.department} />
                      <LaneBadge lane={incident.lane} />
                      <span className="text-[11px] text-mute">{reportCount(incident.report_count, t)}</span>
                    </div>
                    {(incident.silent_sos || incident.combined_risk || exhausted || live || incident.prank_suspected) && (
                      <div className="mt-1.5 flex flex-wrap gap-1.5">
                        {incident.silent_sos && <Pill className="bg-danger/15 text-danger ring-danger/30">{t("badge.silentSos")}</Pill>}
                        {incident.combined_risk && <Pill className="bg-accent-soft text-accent-ink ring-accent/30">{t("badge.linkedRisk")}</Pill>}
                        {exhausted && <Pill className="bg-danger/10 text-danger ring-danger/25">{t("badge.exhausted")}</Pill>}
                        {!exhausted && live && <Pill className="bg-fuchsia-500/10 text-fuchsia-700 ring-fuchsia-500/25 dark:text-fuchsia-300">{t("badge.alerted", { contact: live.contact })}</Pill>}
                        {incident.prank_suspected && <Pill className="bg-surface-2 text-mute ring-line">{t("badge.prank")}</Pill>}
                      </div>
                    )}
                  </div>
                </button>
              </li>
            );
          })}
        </ol>
      </section>
      <section className="relative min-h-[420px]" aria-label={t("incidents.map")}>
        <MapView incidents={ranked} selectedId={selectedId} onSelect={select} />
        {selected && (
          <div className="absolute inset-0 z-[1000] p-3 sm:inset-y-0 sm:left-auto sm:right-0 sm:w-[480px]">
            <IncidentDetail
              key={selected.id}
              incident={selected}
              incidents={state.incidents}
              alerts={state.alerts}
              onClose={() => select(null)}
              onSelect={select}
            />
          </div>
        )}
      </section>
    </div>
  );
}
