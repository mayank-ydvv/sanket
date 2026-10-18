import { ArrowRight, Radio } from "lucide-react";
import { useNavigate } from "react-router";
import { AnimatedList } from "@/components/magicui/animated-list";
import { BlurFade } from "@/components/magicui/blur-fade";
import { FlickeringGrid } from "@/components/magicui/flickering-grid";
import { MorphingText } from "@/components/magicui/morphing-text";
import { PulsatingButton } from "@/components/magicui/pulsating-button";
import { DepartmentBadge, SeverityDot } from "@/components/ui/badges";
import { useTheme } from "@/lib/theme";
import { HERO_PHRASES, SAMPLE_REPORTS } from "./samples";

function FeedItem({ text, language, department, severity }: (typeof SAMPLE_REPORTS)[number]) {
  return (
    <figure className="w-full rounded-xl border border-line bg-surface p-3.5 shadow-card transition hover:border-line-strong">
      <div className="flex items-center justify-between gap-3 text-[11px] text-mute">
        <span className="inline-flex items-center gap-1.5">
          <SeverityDot severity={severity} /> {language}
        </span>
        <DepartmentBadge department={department} />
      </div>
      <p className="mt-2 text-sm leading-snug text-ink">{text}</p>
    </figure>
  );
}

export function Hero() {
  const navigate = useNavigate();
  const { resolved } = useTheme();
  return (
    <section className="relative overflow-hidden">
      <FlickeringGrid
        className="absolute inset-0 -z-10 [mask-image:radial-gradient(ellipse_at_top,white_20%,transparent_70%)]"
        squareSize={4}
        gridGap={6}
        color={resolved === "dark" ? "rgb(234,88,12)" : "rgb(234,88,12)"}
        maxOpacity={resolved === "dark" ? 0.18 : 0.12}
        flickerChance={0.08}
      />
      <div className="mx-auto grid max-w-6xl items-center gap-14 px-4 pb-20 pt-16 sm:px-6 lg:grid-cols-[1.15fr_1fr] lg:pt-24">
        <div>
          <BlurFade delay={0.05}>
            <span className="inline-flex items-center gap-2 rounded-full border border-accent/30 bg-accent-soft px-3 py-1 text-xs font-medium text-accent-ink">
              <Radio className="size-3.5" /> AI emergency triage · built for India
            </span>
          </BlurFade>
          <BlurFade delay={0.15}>
            <h1 className="mt-6 font-display text-4xl font-extrabold leading-[1.08] tracking-tight sm:text-5xl lg:text-6xl">
              When the lines flood,
              <br />
              Sanket finds the <span className="text-accent">signal</span>.
            </h1>
          </BlurFade>
          <BlurFade delay={0.25}>
            <div className="mt-6 h-14 overflow-hidden text-left sm:h-16" aria-hidden>
              <MorphingText texts={HERO_PHRASES} className="mx-0 h-14 max-w-none text-left text-3xl text-ink-2 sm:h-16 sm:text-4xl lg:text-[2.6rem]" />
            </div>
          </BlurFade>
          <BlurFade delay={0.35}>
            <p className="mt-4 max-w-xl text-lg leading-relaxed text-ink-2">
              Calls, SMS and WhatsApp in any Indian language become a short, ranked list of real incidents, merged,
              routed to the right team and dispatched in seconds, at a fraction of the cost of sending everything to a
              large LLM.
            </p>
          </BlurFade>
          <BlurFade delay={0.45}>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <PulsatingButton
                onClick={() => navigate("/signup")}
                pulseColor="rgba(234, 88, 12, 0.45)"
                className="h-12 rounded-xl bg-accent px-6 text-base font-semibold text-white"
              >
                <span className="inline-flex items-center gap-2">
                  Open the control room <ArrowRight className="size-4" />
                </span>
              </PulsatingButton>
              <a href="#how" className="inline-flex h-12 items-center rounded-xl px-5 text-sm font-medium text-ink-2 transition hover:text-ink">
                See how it works
              </a>
            </div>
          </BlurFade>
        </div>

        <BlurFade delay={0.3} direction="left">
          <div className="relative">
            <div className="absolute -inset-6 -z-10 rounded-[2rem] bg-gradient-to-br from-accent/15 via-transparent to-live/15 blur-2xl" />
            <div className="rounded-3xl border border-line bg-surface-2/80 p-4 shadow-card backdrop-blur">
              <div className="mb-3 flex items-center justify-between px-1">
                <p className="text-sm font-semibold">Incoming reports</p>
                <span className="inline-flex items-center gap-1.5 text-xs text-mute">
                  <span className="size-2 animate-pulse rounded-full bg-good" /> live
                </span>
              </div>
              <div className="relative h-[380px] overflow-hidden">
                <AnimatedList delay={1800} className="gap-2.5">
                  {SAMPLE_REPORTS.map((report) => (
                    <FeedItem key={report.text} {...report} />
                  ))}
                </AnimatedList>
                <div className="pointer-events-none absolute inset-x-0 bottom-0 h-24 bg-gradient-to-t from-surface-2 to-transparent" />
              </div>
            </div>
          </div>
        </BlurFade>
      </div>
    </section>
  );
}
