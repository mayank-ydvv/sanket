import { ArrowRight, BellRing, CloudRain, FileText, Inbox, Siren } from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";
import { Link } from "react-router";
import { AnimatedCircularProgressBar } from "@/components/magicui/animated-circular-progress-bar";
import { BlurFade } from "@/components/magicui/blur-fade";
import { MagicCard } from "@/components/magicui/magic-card";
import { NumberTicker } from "@/components/magicui/number-ticker";
import { PulsatingButton } from "@/components/magicui/pulsating-button";
import { DepartmentBadge, LaneBadge, SeverityChip, SeverityDot } from "@/components/ui/badges";
import { Card, CardHeader } from "@/components/ui/Card";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLive } from "@/lib/live";
import { formatInr, liveAlertFor, rankIncidents, waitingLabel } from "@/lib/store";
import { useTheme } from "@/lib/theme";
import { useNow } from "@/hooks/useNow";

function Kpi({ label, value, icon, tone }: { label: string; value: number; icon: ReactNode; tone: string }) {
  const { resolved } = useTheme();
  return (
    <MagicCard
      className="rounded-2xl"
      gradientColor={resolved === "dark" ? "#1c263f" : "#fff6ef"}
      gradientFrom="#ea580c"
      gradientTo="#0ea5e9"
    >
      <div className="flex items-start justify-between p-5">
        <div>
          <p className="text-sm text-mute">{label}</p>
          <p className="mt-2 font-display text-3xl font-bold tracking-tight">
            {value > 0 ? <NumberTicker value={value} className="text-ink" /> : <span className="text-ink">0</span>}
          </p>
        </div>
        <span className={`grid size-10 place-items-center rounded-xl ${tone}`}>{icon}</span>
      </div>
    </MagicCard>
  );
}

function DisasterPanel() {
  const { state } = useLive();
  const { resolved } = useTheme();
  const [error, setError] = useState<string | null>(null);
  const sim = state.simulation;
  const running = sim?.running ?? false;
  const pct = sim?.total ? Math.round((100 * sim.decided) / sim.total) : 0;
  const start = async () => {
    setError(null);
    try {
      await api("/simulate/disaster?n=500&seconds=10&scenario=flood", { method: "POST" });
    } catch (exc) {
      setError(exc instanceof ApiError && exc.status === 409 ? "A run is already in progress." : "Could not start the simulation.");
    }
  };
  return (
    <Card className="overflow-hidden">
      <CardHeader title="Disaster mode" subtitle="500 simulated flood reports in 10 seconds, through the real pipeline." />
      <div className="flex flex-col items-center gap-5 p-6 sm:flex-row">
        <AnimatedCircularProgressBar
          value={pct}
          gaugePrimaryColor="#ea580c"
          gaugeSecondaryColor={resolved === "dark" ? "rgba(255,255,255,0.08)" : "rgba(15,23,42,0.08)"}
          className="size-28 shrink-0 text-xl font-bold"
        />
        <div className="flex-1 text-center sm:text-left">
          {sim?.total ? (
            <p className="text-sm text-ink-2">
              <span className="font-mono font-semibold text-ink">{sim.decided}</span> of {sim.total} reports triaged
              {sim.decided_s != null && (
                <>
                  {" "}in <span className="font-mono font-semibold text-ink">{sim.decided_s.toFixed(1)} s</span>
                </>
              )}
              .
            </p>
          ) : (
            <p className="text-sm text-ink-2">Watch a monsoon surge collapse into a dozen ranked incidents.</p>
          )}
          <div className="mt-4 flex justify-center sm:justify-start">
            {running ? (
              <span className="inline-flex h-10 items-center gap-2 rounded-xl bg-surface-2 px-4 text-sm font-medium text-ink-2">
                <CloudRain className="size-4 animate-pulse text-accent" /> Surge in progress…
              </span>
            ) : (
              <PulsatingButton onClick={start} pulseColor="rgba(234, 88, 12, 0.4)" className="h-10 rounded-xl bg-accent px-5 text-sm font-semibold text-white">
                <span className="inline-flex items-center gap-2">
                  <CloudRain className="size-4" /> Start flood surge
                </span>
              </PulsatingButton>
            )}
          </div>
          {error && <p className="mt-2 text-xs text-danger">{error}</p>}
        </div>
      </div>
    </Card>
  );
}

function greeting(): string {
  const hour = new Date().getHours();
  return hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
}

export default function Overview() {
  const { user } = useAuth();
  const { state } = useLive();
  const now = useNow(5000);
  const ranked = useMemo(() => rankIncidents(state.incidents), [state.incidents]);
  const open = ranked.filter((i) => i.status !== "resolved");
  const review = open.filter((i) => i.lane === "review" && i.status === "open").length;
  const alerting = open.filter((i) => liveAlertFor(state.alerts, i.id)).length;
  const latest = useMemo(
    () => [...state.reports.values()].sort((a, b) => b.received_at - a.received_at).slice(0, 7),
    [state.reports],
  );
  const cost = state.cost;

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6 lg:p-8">
      <BlurFade>
        <h2 className="font-display text-2xl font-bold tracking-tight">
          {greeting()}, {user?.name.split(" ")[0]}
        </h2>
        <p className="mt-1 text-sm text-mute">Here's the situation right now.</p>
      </BlurFade>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <BlurFade delay={0.05}><Kpi label="Open incidents" value={open.length} icon={<Siren className="size-5" />} tone="bg-accent-soft text-accent" /></BlurFade>
        <BlurFade delay={0.1}><Kpi label="Needs human review" value={review} icon={<Inbox className="size-5" />} tone="bg-yellow-500/15 text-yellow-600 dark:text-yellow-300" /></BlurFade>
        <BlurFade delay={0.15}><Kpi label="Alerts awaiting ack" value={alerting} icon={<BellRing className="size-5" />} tone="bg-fuchsia-500/15 text-fuchsia-600 dark:text-fuchsia-300" /></BlurFade>
        <BlurFade delay={0.2}><Kpi label="Reports received" value={state.reports.size} icon={<FileText className="size-5" />} tone="bg-live-soft text-live" /></BlurFade>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
        <BlurFade delay={0.1}>
          <Card>
            <CardHeader
              title="Highest priority"
              subtitle="Most severe first, then longest waiting."
              action={
                <Link to="/app/incidents" className="inline-flex items-center gap-1 text-sm font-medium text-accent hover:underline">
                  All incidents <ArrowRight className="size-4" />
                </Link>
              }
            />
            {open.length === 0 ? (
              <p className="px-5 py-12 text-center text-sm text-mute">No open incidents. Start a flood surge to see Sanket at work.</p>
            ) : (
              <ul className="divide-y divide-line">
                {open.slice(0, 6).map((incident) => (
                  <li key={incident.id}>
                    <Link to={`/app/incidents?focus=${incident.id}`} className="flex items-center gap-4 px-5 py-3.5 transition hover:bg-surface-2">
                      <SeverityChip severity={incident.severity} size="sm" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">{incident.title}</p>
                        <div className="mt-1 flex flex-wrap gap-1.5">
                          <DepartmentBadge department={incident.department} />
                          <LaneBadge lane={incident.lane} />
                          {incident.combined_risk && <span className="text-[11px] font-medium text-accent">⚠ linked risk</span>}
                        </div>
                      </div>
                      <div className="text-right text-xs text-mute">
                        <p className="font-mono">{waitingLabel(incident.first_seen, now)}</p>
                        <p>{incident.report_count} reports</p>
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </BlurFade>

        <div className="space-y-6">
          <BlurFade delay={0.15}>
            <DisasterPanel />
          </BlurFade>
          <BlurFade delay={0.2}>
            <Card>
              <CardHeader title="LLM cost" subtitle="List price for tokens used, vs every report sent to a large reasoning model." />
              <div className="grid grid-cols-2 gap-px bg-line">
                <div className="bg-surface p-5">
                  <p className="text-xs text-mute">Sanket</p>
                  <p className="mt-1 font-mono text-2xl font-semibold text-good">{formatInr(cost?.sanket_inr ?? 0)}</p>
                  <p className="mt-1 text-xs text-mute">{cost?.llm_calls ?? 0} LLM calls</p>
                </div>
                <div className="bg-surface p-5">
                  <p className="text-xs text-mute">All to a large LLM</p>
                  <p className="mt-1 font-mono text-2xl font-semibold text-danger">{formatInr(cost?.counterfactual_inr ?? 0)}</p>
                  <p className="mt-1 text-xs text-mute">{cost && cost.counterfactual_inr > 0 ? `${cost.saved_pct.toFixed(1)}% saved` : "—"}</p>
                </div>
              </div>
            </Card>
          </BlurFade>
        </div>
      </div>

      <BlurFade delay={0.15}>
        <Card>
          <CardHeader title="Live feed" subtitle="Newest reports from every channel." />
          {latest.length === 0 ? (
            <p className="px-5 py-10 text-center text-sm text-mute">Waiting for reports…</p>
          ) : (
            <ul className="divide-y divide-line">
              {latest.map((report) => (
                <li key={report.id} className="flex items-center gap-3 px-5 py-3">
                  <SeverityDot severity={report.decision?.severity ?? 1} />
                  <span className="w-16 shrink-0 text-[11px] uppercase tracking-wide text-mute">{report.channel}</span>
                  <p className="min-w-0 flex-1 truncate text-sm">{report.raw_text || <em className="text-mute">silent call</em>}</p>
                  {report.decision && <DepartmentBadge department={report.decision.department} />}
                  {report.refining && <span className="text-[11px] text-live">re-checking…</span>}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </BlurFade>
    </div>
  );
}
