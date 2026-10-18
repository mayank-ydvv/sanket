import { ArrowRight, BellRing, BrainCircuit, CloudRain, IndianRupee, Languages, ShieldCheck } from "lucide-react";
import { useNavigate } from "react-router";
import { AnimatedCircularProgressBar } from "@/components/magicui/animated-circular-progress-bar";
import { BentoCard, BentoGrid } from "@/components/magicui/bento-grid";
import { BlurFade } from "@/components/magicui/blur-fade";
import { DottedMap } from "@/components/magicui/dotted-map";
import { Marquee } from "@/components/magicui/marquee";
import { NumberTicker } from "@/components/magicui/number-ticker";
import { PulsatingButton } from "@/components/magicui/pulsating-button";
import { Ripple } from "@/components/magicui/ripple";
import { DepartmentBadge, LaneBadge, SeverityDot } from "@/components/ui/badges";
import { Logo } from "@/components/ui/Logo";
import { useTheme } from "@/lib/theme";
import { SAMPLE_REPORTS } from "./samples";

function ReportPill({ text, language, department, severity }: (typeof SAMPLE_REPORTS)[number]) {
  return (
    <div className="flex w-80 items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3 shadow-card">
      <SeverityDot severity={severity} />
      <p className="flex-1 truncate text-sm text-ink">{text}</p>
      <span className="shrink-0 text-[11px] text-mute">{language}</span>
      <DepartmentBadge department={department} />
    </div>
  );
}

export function ReportMarquee() {
  const half = Math.ceil(SAMPLE_REPORTS.length / 2);
  return (
    <section aria-label="Example reports" className="relative py-10">
      <Marquee pauseOnHover className="[--duration:45s]">
        {SAMPLE_REPORTS.slice(0, half).map((r) => (
          <ReportPill key={r.text} {...r} />
        ))}
      </Marquee>
      <Marquee reverse pauseOnHover className="[--duration:50s]">
        {SAMPLE_REPORTS.slice(half).map((r) => (
          <ReportPill key={r.text} {...r} />
        ))}
      </Marquee>
      <div className="pointer-events-none absolute inset-y-0 left-0 w-1/5 bg-gradient-to-r from-bg" />
      <div className="pointer-events-none absolute inset-y-0 right-0 w-1/5 bg-gradient-to-l from-bg" />
    </section>
  );
}

const FEATURE_BG = "absolute inset-x-6 top-6 [mask-image:linear-gradient(to_bottom,black_60%,transparent)]";

const FEATURES = [
  {
    Icon: CloudRain,
    name: "Disaster mode",
    description: "500 flood reports in 10 seconds collapse into a dozen ranked incidents on the live map.",
    className: "col-span-3 lg:col-span-2",
    background: (
      <div className={`${FEATURE_BG} flex items-end gap-1.5`}>
        {[38, 62, 45, 80, 52, 95, 70, 58, 88, 41, 66, 74].map((h, i) => (
          <div key={i} className="flex-1 rounded-t-md bg-gradient-to-t from-accent/70 to-accent/20" style={{ height: `${h * 1.1}px` }} />
        ))}
      </div>
    ),
  },
  {
    Icon: BellRing,
    name: "Silent SOS",
    description: "Tap codes, repeated digits or a silent open line are recognised and escalated to police, quietly.",
    className: "col-span-3 lg:col-span-1",
    background: (
      <div className={`${FEATURE_BG} flex items-center justify-center gap-2 pt-10`} aria-hidden>
        {[0, 0, 0, 1, 1, 1, 0, 0, 0].map((dash, i) => (
          <span key={i} className={`h-3 rounded-full bg-accent/50 ${dash ? "w-8" : "w-3"} ${i % 3 === 2 ? "mr-3" : ""}`} />
        ))}
      </div>
    ),
  },
  {
    Icon: BrainCircuit,
    name: "Cross-report reasoning",
    description: "'Smoke on the 5th floor' + 'gas smell near the lift' becomes one incident flagged for explosion risk.",
    className: "col-span-3 lg:col-span-1",
    background: (
      <div className={`${FEATURE_BG} space-y-2 text-xs`}>
        <div className="rounded-lg border border-line bg-surface-2 px-3 py-2">smoke on the 5th floor</div>
        <div className="ml-6 rounded-lg border border-line bg-surface-2 px-3 py-2">gas smell near the lift</div>
        <div className="rounded-lg border border-accent/40 bg-accent-soft px-3 py-2 font-medium text-accent-ink">⚠ possible gas explosion risk</div>
      </div>
    ),
  },
  {
    Icon: Languages,
    name: "Five languages, one board",
    description: "Hindi, Hinglish, English, Tamil and Bengali, typos and panic included.",
    className: "col-span-3 lg:col-span-1",
    background: (
      <Marquee vertical className={`${FEATURE_BG} h-44 [--duration:18s]`}>
        {["आग लगी है", "aag lagi hai", "Fire!", "தீ பிடித்துள்ளது", "আগুন লেগেছে"].map((t) => (
          <span key={t} className="text-lg font-semibold text-ink-2/50">
            {t}
          </span>
        ))}
      </Marquee>
    ),
  },
  {
    Icon: ShieldCheck,
    name: "Humans decide",
    description: "Nothing is ever auto-dismissed. Confidence gates send uncertain calls to a dispatcher, with an audit trail.",
    className: "col-span-3 lg:col-span-1",
    background: (
      <div className={`${FEATURE_BG} flex flex-col items-start gap-2 pt-2`}>
        <LaneBadge lane="auto" />
        <LaneBadge lane="confirm" />
        <LaneBadge lane="review" />
      </div>
    ),
  },
];

export function Features() {
  return (
    <section id="features" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-24 sm:px-6">
      <BlurFade inView>
        <p className="text-sm font-semibold uppercase tracking-widest text-accent">Features</p>
        <h2 className="mt-3 max-w-2xl font-display text-3xl font-bold tracking-tight sm:text-4xl">
          Built for the moment the phones won't stop ringing.
        </h2>
      </BlurFade>
      <BentoGrid className="mt-12">
        {FEATURES.map((feature) => (
          <BentoCard key={feature.name} {...feature} href="/signup" cta="Try it" />
        ))}
      </BentoGrid>
    </section>
  );
}

function Stat({ value, decimals = 0, prefix, suffix, label }: { value: number; decimals?: number; prefix?: string; suffix?: string; label: string }) {
  return (
    <div className="rounded-2xl border border-line bg-surface p-6 shadow-card">
      <p className="font-display text-4xl font-extrabold tracking-tight">
        {prefix}
        <NumberTicker value={value} decimalPlaces={decimals} className="text-ink" />
        {suffix}
      </p>
      <p className="mt-2 text-sm leading-snug text-mute">{label}</p>
    </div>
  );
}

export function Results() {
  const { resolved } = useTheme();
  return (
    <section id="results" className="scroll-mt-20 border-y border-line bg-surface/60">
      <div className="mx-auto max-w-6xl px-4 py-24 sm:px-6">
        <BlurFade inView>
          <p className="text-sm font-semibold uppercase tracking-widest text-accent">Measured, not promised</p>
          <h2 className="mt-3 max-w-2xl font-display text-3xl font-bold tracking-tight sm:text-4xl">
            Numbers from a live 500-report flood run and a held-out benchmark.
          </h2>
        </BlurFade>
        <div className="mt-12 grid items-stretch gap-5 lg:grid-cols-[1fr_1fr_1fr_auto]">
          <Stat value={12} label="incidents from 500 flood reports, merged across 5 languages" />
          <Stat value={10.2} decimals={1} suffix=" s" label="for all 500 reports to be triaged and on the board" />
          <Stat value={99.8} decimals={1} suffix="%" label="cheaper than sending every report to a large reasoning model" />
          <div className="flex flex-col items-center justify-center rounded-2xl border border-line bg-surface p-6 shadow-card">
            <AnimatedCircularProgressBar
              value={98}
              gaugePrimaryColor="#ea580c"
              gaugeSecondaryColor={resolved === "dark" ? "rgba(255,255,255,0.08)" : "rgba(15,23,42,0.08)"}
              className="size-32 text-2xl font-bold"
            />
            <p className="mt-3 max-w-[11rem] text-center text-sm text-mute">triage accuracy on held-out reports</p>
          </div>
        </div>
      </div>
    </section>
  );
}

export function Coverage() {
  const { resolved } = useTheme();
  return (
    <section className="mx-auto grid max-w-6xl items-center gap-10 px-4 py-24 sm:px-6 lg:grid-cols-2">
      <BlurFade inView>
        <p className="text-sm font-semibold uppercase tracking-widest text-accent">Where it runs</p>
        <h2 className="mt-3 font-display text-3xl font-bold tracking-tight sm:text-4xl">Demo district: Noida, Uttar Pradesh.</h2>
        <p className="mt-4 max-w-md text-ink-2">
          Landmarks resolve offline from a built-in gazetteer, everything else through OpenStreetMap. Point it at any
          district by changing one setting.
        </p>
      </BlurFade>
      <BlurFade inView delay={0.15}>
        <div className="relative overflow-hidden rounded-3xl border border-line bg-surface p-6">
          <DottedMap
            markers={[{ lat: 28.5355, lng: 77.391, size: 1.2, pulse: true }]}
            markerColor="#ea580c"
            dotColor={resolved === "dark" ? "rgba(229,233,242,0.28)" : "rgba(15,23,42,0.25)"}
            className="w-full"
          />
        </div>
      </BlurFade>
    </section>
  );
}

export function FinalCta() {
  const navigate = useNavigate();
  return (
    <section className="relative mx-4 mb-16 overflow-hidden rounded-3xl border border-line bg-surface px-6 py-20 text-center sm:mx-6 lg:mx-auto lg:max-w-6xl">
      <Ripple mainCircleSize={260} numCircles={6} />
      <div className="relative">
        <h2 className="font-display text-3xl font-bold tracking-tight sm:text-4xl">Ready for the next surge?</h2>
        <p className="mx-auto mt-3 max-w-lg text-ink-2">Create an account, open the control room, and press Disaster mode.</p>
        <div className="mt-8 flex justify-center">
          <PulsatingButton
            onClick={() => navigate("/signup")}
            pulseColor="rgba(234, 88, 12, 0.45)"
            className="h-12 rounded-xl bg-accent px-6 text-base font-semibold text-white"
          >
            <span className="inline-flex items-center gap-2">
              Get started free <ArrowRight className="size-4" />
            </span>
          </PulsatingButton>
        </div>
      </div>
    </section>
  );
}

export function Footer() {
  return (
    <footer className="border-t border-line">
      <div className="mx-auto flex max-w-6xl flex-col items-start justify-between gap-4 px-4 py-10 text-sm text-mute sm:flex-row sm:items-center sm:px-6">
        <Logo />
        <p className="flex items-center gap-1.5">
          <IndianRupee className="size-3.5" /> Runs on free tiers · synthetic demo data · humans decide
        </p>
      </div>
    </footer>
  );
}
