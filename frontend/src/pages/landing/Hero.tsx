import { ArrowRight, Languages, Radio } from "lucide-react";
import { useNavigate } from "react-router";
import { AnimatedList } from "@/components/magicui/animated-list";
import { BlurFade } from "@/components/magicui/blur-fade";
import { FlickeringGrid } from "@/components/magicui/flickering-grid";
import { MorphingText } from "@/components/magicui/morphing-text";
import { PulsatingButton } from "@/components/magicui/pulsating-button";
import { DepartmentBadge, SeverityDot } from "@/components/ui/badges";
import { useI18n } from "@/lib/i18n";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { HERO_PHRASES, SAMPLE_REPORTS } from "./samples";

function FeedItem({ text, english, language, department, severity }: (typeof SAMPLE_REPORTS)[number]) {
  const { t } = useI18n();
  return (
    <figure className="w-full rounded-xl border border-line bg-surface p-3.5 shadow-card transition hover:border-line-strong">
      <div className="flex items-center justify-between gap-3 text-[11px] text-mute">
        <span className="inline-flex items-center gap-1.5">
          <SeverityDot severity={severity} /> {t(language)}
        </span>
        <DepartmentBadge department={department} />
      </div>
      <p className="mt-2 text-sm leading-snug text-ink">{text}</p>
      {english && (
        <p className="mt-1.5 flex gap-1.5 text-xs leading-snug text-mute" lang="en">
          <Languages className="mt-px size-3 shrink-0" aria-hidden /> {english}
        </p>
      )}
    </figure>
  );
}

export function Hero() {
  const navigate = useNavigate();
  const { t, lang } = useI18n();
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
              <Radio className="size-3.5" /> {t("hero.badge")}
            </span>
          </BlurFade>
          <BlurFade delay={0.15}>
            <h1
              className={cn(
                "mt-6 font-display font-extrabold tracking-tight",
                lang === "ta" ? "text-3xl leading-[1.25] sm:text-4xl lg:text-[2.75rem]" : "text-4xl leading-[1.08] sm:text-5xl lg:text-6xl",
              )}
            >
              {t("hero.line1")}
              <br />
              {t("hero.line2a")}
              <span className="text-accent">{t("hero.line2b")}</span>
              {t("hero.line2c")}
            </h1>
          </BlurFade>
          <BlurFade delay={0.25}>
            <div className="mt-6 h-14 overflow-hidden text-left sm:h-16" aria-hidden>
              <MorphingText texts={HERO_PHRASES} className="mx-0 h-14 max-w-none text-left text-3xl text-ink-2 sm:h-16 sm:text-4xl lg:text-[2.6rem]" />
            </div>
          </BlurFade>
          <BlurFade delay={0.35}>
            <p className="mt-4 max-w-xl text-lg leading-relaxed text-ink-2">{t("hero.body")}</p>
          </BlurFade>
          <BlurFade delay={0.45}>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <PulsatingButton
                onClick={() => navigate("/signup")}
                pulseColor="rgba(234, 88, 12, 0.45)"
                className="h-12 rounded-xl bg-accent px-6 text-base font-semibold text-white"
              >
                <span className="inline-flex items-center gap-2">
                  {t("hero.cta")} <ArrowRight className="size-4" />
                </span>
              </PulsatingButton>
              <a href="#how" className="inline-flex h-12 items-center rounded-xl px-5 text-sm font-medium text-ink-2 transition hover:text-ink">
                {t("hero.see")}
              </a>
            </div>
          </BlurFade>
        </div>

        <BlurFade delay={0.3} direction="left">
          <div className="relative">
            <div className="absolute -inset-6 -z-10 rounded-[2rem] bg-gradient-to-br from-accent/15 via-transparent to-live/15 blur-2xl" />
            <div className="rounded-3xl border border-line bg-surface-2/80 p-4 shadow-card backdrop-blur">
              <div className="mb-3 flex items-center justify-between px-1">
                <p className="text-sm font-semibold">{t("hero.incoming")}</p>
                <span className="inline-flex items-center gap-1.5 text-xs text-mute">
                  <span className="size-2 animate-pulse rounded-full bg-good" /> {t("hero.live")}
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
