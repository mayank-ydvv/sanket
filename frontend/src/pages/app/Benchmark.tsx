import { useEffect, useState } from "react";
import { AnimatedCircularProgressBar } from "@/components/magicui/animated-circular-progress-bar";
import { BlurFade } from "@/components/magicui/blur-fade";
import { AccuracyCostChart } from "@/components/benchmark/AccuracyCostChart";
import { type Benchmark, HYBRID, latencyLabel } from "@/components/benchmark/types";
import { Card, CardHeader } from "@/components/ui/Card";
import { ApiError, api } from "@/lib/api";
import { formatInr } from "@/lib/store";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

const COLUMNS = ["Approach", "Triage", "Hidden 50", "Emergency P / R / F1", "Dept", "Sev MAE", "Silent SOS", "p50 / p95", "LLM calls", "₹ / 1,000"];

export default function BenchmarkPage() {
  const { resolved } = useTheme();
  const [data, setData] = useState<Benchmark | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Benchmark>("/benchmark")
      .then(setData)
      .catch((exc) => setError(exc instanceof ApiError ? exc.message : "Could not load the benchmark."));
  }, []);

  if (error) return <p className="p-10 text-center text-sm text-mute">{error}</p>;
  if (!data) return <p className="p-10 text-center text-sm text-mute">Loading benchmark…</p>;
  const languages = Object.keys(data.approaches[0]?.per_language ?? {}).sort();
  const track = resolved === "dark" ? "rgba(255,255,255,0.08)" : "rgba(15,23,42,0.08)";

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6 lg:p-8">
      <BlurFade>
        <p className="max-w-3xl text-sm text-mute">
          {data.n} held-out multilingual reports streamed at {data.reports_per_second}/s · {data.run_at} · free-tier APIs,
          list-price cost. Triage accuracy = emergency call right and, for real emergencies, the right department.
        </p>
      </BlurFade>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        {data.approaches.map((a, i) => (
          <BlurFade key={a.approach} delay={0.05 * i} className="h-full">
            <Card className={cn("flex h-full flex-col items-center p-5 text-center", a.approach === HYBRID && "border-accent/50 ring-2 ring-accent/15")}>
              <AnimatedCircularProgressBar
                value={Math.round(a.triage_acc * 100)}
                gaugePrimaryColor={a.approach === HYBRID ? "#ea580c" : resolved === "dark" ? "#8b95ab" : "#64748b"}
                gaugeSecondaryColor={track}
                className="size-24 text-lg font-bold"
              />
              <p className="mt-3 text-sm font-semibold">{a.approach}</p>
              <p className="text-xs text-mute">{formatInr(a.cost_per_1000_inr)} per 1,000</p>
            </Card>
          </BlurFade>
        ))}
      </div>

      <BlurFade delay={0.1}>
        <Card>
          <CardHeader title="Accuracy vs cost" subtitle="Top-left is best. Hover a point for details." />
          <div className="p-4 sm:p-6">
            <AccuracyCostChart data={data.approaches} />
          </div>
        </Card>
      </BlurFade>

      <BlurFade delay={0.15}>
        <Card className="overflow-hidden">
          <CardHeader title="All metrics" />
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-2 text-left text-[11px] uppercase tracking-wider text-mute">
                <tr>{COLUMNS.map((c) => <th key={c} className="whitespace-nowrap px-4 py-2.5 font-medium">{c}</th>)}</tr>
              </thead>
              <tbody className="divide-y divide-line font-mono text-[13px]">
                {data.approaches.map((a) => (
                  <tr key={a.approach} className={cn(a.approach === HYBRID && "bg-accent-soft/50")}>
                    <td className="whitespace-nowrap px-4 py-3 font-sans font-medium">{a.approach}</td>
                    <td className="px-4 py-3">{(a.triage_acc * 100).toFixed(1)}%</td>
                    <td className="px-4 py-3">{(a.triage_acc_hidden50 * 100).toFixed(0)}%</td>
                    <td className="whitespace-nowrap px-4 py-3">
                      {a.emergency.precision.toFixed(2)} / {a.emergency.recall.toFixed(2)} / {a.emergency.f1.toFixed(2)}
                    </td>
                    <td className="px-4 py-3">{(a.department_acc * 100).toFixed(1)}%</td>
                    <td className="px-4 py-3">{a.severity_mae.toFixed(2)}</td>
                    <td className="px-4 py-3">{a.silent_sos_caught}</td>
                    <td className="whitespace-nowrap px-4 py-3">{latencyLabel(a.latency_ms.median)} / {latencyLabel(a.latency_ms.p95)}</td>
                    <td className="px-4 py-3">{a.llm_calls}</td>
                    <td className="px-4 py-3">{formatInr(a.cost_per_1000_inr)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </BlurFade>

      <div className="grid gap-6 lg:grid-cols-2">
        <BlurFade delay={0.2}>
          <Card className="h-full overflow-hidden">
            <CardHeader title="By language" subtitle="Triage accuracy per language." />
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-surface-2 text-left text-[11px] uppercase tracking-wider text-mute">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">Approach</th>
                    {languages.map((l) => <th key={l} className="px-4 py-2.5 font-medium">{l}</th>)}
                  </tr>
                </thead>
                <tbody className="divide-y divide-line font-mono text-[13px]">
                  {data.approaches.map((a) => (
                    <tr key={a.approach}>
                      <td className="whitespace-nowrap px-4 py-2.5 font-sans">{a.approach}</td>
                      {languages.map((l) => <td key={l} className="px-4 py-2.5">{((a.per_language[l]?.triage_acc ?? 0) * 100).toFixed(0)}%</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </BlurFade>
        {data.local_gate_curve && data.local_gate_curve.length > 0 && (
          <BlurFade delay={0.25}>
            <Card className="h-full overflow-hidden">
              <CardHeader title="Local confidence gate" subtitle="How much the local model could decide alone, and how well." />
              <table className="w-full text-sm">
                <thead className="bg-surface-2 text-left text-[11px] uppercase tracking-wider text-mute">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">Gate</th>
                    <th className="px-4 py-2.5 font-medium">Kept local</th>
                    <th className="px-4 py-2.5 font-medium">Accuracy on those</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line font-mono text-[13px]">
                  {data.local_gate_curve.map((c) => (
                    <tr key={c.gate}>
                      <td className="px-4 py-2.5">≥ {c.gate.toFixed(1)}</td>
                      <td className="px-4 py-2.5">{(c.coverage * 100).toFixed(0)}%</td>
                      <td className="px-4 py-2.5">{c.coverage ? `${(c.triage_acc_on_covered * 100).toFixed(1)}%` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </BlurFade>
        )}
      </div>

      <BlurFade delay={0.3}>
        <Card>
          <CardHeader title="Notes" subtitle="How to read these numbers honestly." />
          <ul className="list-disc space-y-1.5 px-9 py-4 text-sm text-ink-2">
            {data.approaches.flatMap((a) => a.notes.map((n) => <li key={a.approach + n}><b className="text-ink">{a.approach}:</b> {n}</li>))}
            {data.approaches.filter((a) => a.unanswered > 0).map((a) => (
              <li key={`${a.approach}-unanswered`}><b className="text-ink">{a.approach}:</b> {a.unanswered} reports got no answer (provider limits) and are scored as missed.</li>
            ))}
            {data.notes.map((n) => <li key={n}>{n}</li>)}
          </ul>
        </Card>
      </BlurFade>
    </div>
  );
}
