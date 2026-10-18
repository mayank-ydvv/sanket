import { Ambulance, CloudRain, Flame, Globe, MessageCircle, MessageSquare, Phone, Shield, Zap } from "lucide-react";
import { forwardRef, type ReactNode, useRef } from "react";
import { AnimatedBeam } from "@/components/magicui/animated-beam";
import { BlurFade } from "@/components/magicui/blur-fade";
import { Ripple } from "@/components/magicui/ripple";
import { useI18n } from "@/lib/i18n";
import type { MessageKey } from "@/lib/messages";
import { cn } from "@/lib/utils";

const Node = forwardRef<HTMLDivElement, { children: ReactNode; label: string; className?: string }>(function Node(
  { children, label, className },
  ref,
) {
  return (
    <div className="flex flex-col items-center gap-1.5">
      <div
        ref={ref}
        className={cn("z-10 grid size-12 place-items-center rounded-full border border-line bg-surface text-ink-2 shadow-card", className)}
      >
        {children}
      </div>
      <span className="text-[11px] font-medium text-mute">{label}</span>
    </div>
  );
});

const STEPS: { title: MessageKey; text: MessageKey }[] = [
  { title: "how.understand", text: "how.understandText" },
  { title: "how.merge", text: "how.mergeText" },
  { title: "how.dispatch", text: "how.dispatchText" },
];

export function HowItWorks() {
  const { t } = useI18n();
  const container = useRef<HTMLDivElement>(null);
  const inputs = [useRef<HTMLDivElement>(null), useRef<HTMLDivElement>(null), useRef<HTMLDivElement>(null), useRef<HTMLDivElement>(null)];
  const hub = useRef<HTMLDivElement>(null);
  const outputs = [useRef<HTMLDivElement>(null), useRef<HTMLDivElement>(null), useRef<HTMLDivElement>(null), useRef<HTMLDivElement>(null), useRef<HTMLDivElement>(null)];
  const inputNodes = [
    { label: t("how.call"), icon: <Phone className="size-5" /> },
    { label: t("how.sms"), icon: <MessageSquare className="size-5" /> },
    { label: t("how.whatsapp"), icon: <MessageCircle className="size-5" /> },
    { label: t("how.web"), icon: <Globe className="size-5" /> },
  ];
  const outputNodes = [
    { label: t("dept.fire"), icon: <Flame className="size-5 text-orange-500" /> },
    { label: t("dept.police"), icon: <Shield className="size-5 text-blue-500" /> },
    { label: t("dept.medical"), icon: <Ambulance className="size-5 text-rose-500" /> },
    { label: t("dept.disaster"), icon: <CloudRain className="size-5 text-violet-500" /> },
    { label: t("dept.utilities"), icon: <Zap className="size-5 text-amber-500" /> },
  ];

  return (
    <section id="how" className="scroll-mt-20 border-y border-line bg-surface/60">
      <div className="mx-auto max-w-6xl px-4 py-24 sm:px-6">
        <BlurFade inView>
          <p className="text-sm font-semibold uppercase tracking-widest text-accent">{t("land.how")}</p>
          <h2 className="mt-3 max-w-2xl font-display text-3xl font-bold tracking-tight sm:text-4xl">
            {t("how.title")}
          </h2>
        </BlurFade>

        <div ref={container} className="relative mt-14 flex items-center justify-between gap-6 overflow-hidden rounded-3xl border border-line bg-bg px-6 py-10 sm:px-14">
          <div className="flex flex-col gap-5">
            {inputNodes.map((node, i) => (
              <Node key={node.label} ref={inputs[i]} label={node.label}>
                {node.icon}
              </Node>
            ))}
          </div>
          <div className="relative grid size-40 place-items-center">
            <Ripple mainCircleSize={110} numCircles={5} className="-inset-32 mask-[radial-gradient(circle,white_35%,transparent_70%)]" />
            <div ref={hub} className="z-10 grid size-20 place-items-center rounded-2xl bg-accent text-white shadow-lg shadow-accent/30">
              <svg viewBox="0 0 24 24" className="size-9" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <path d="M3 13h4l2.5-6 4 11 2.5-5H21" />
              </svg>
            </div>
          </div>
          <div className="flex flex-col gap-3">
            {outputNodes.map((node, i) => (
              <Node key={node.label} ref={outputs[i]} label={node.label}>
                {node.icon}
              </Node>
            ))}
          </div>
          {inputs.map((ref, i) => (
            <AnimatedBeam key={`in-${i}`} containerRef={container} fromRef={ref} toRef={hub} curvature={(i - 1.5) * 18} duration={4} delay={i * 0.4} gradientStartColor="#ea580c" gradientStopColor="#f59e0b" />
          ))}
          {outputs.map((ref, i) => (
            <AnimatedBeam key={`out-${i}`} containerRef={container} fromRef={hub} toRef={ref} curvature={(i - 2) * 14} duration={4} delay={1.2 + i * 0.3} gradientStartColor="#0ea5e9" gradientStopColor="#22d3ee" />
          ))}
        </div>

        <div className="mt-12 grid gap-6 sm:grid-cols-3">
          {STEPS.map((step, i) => (
            <BlurFade key={step.title} inView delay={0.1 * i}>
              <div className="rounded-2xl border border-line bg-surface p-6">
                <span className="font-mono text-sm font-semibold text-accent">0{i + 1}</span>
                <h3 className="mt-2 font-display text-lg font-semibold">{t(step.title)}</h3>
                <p className="mt-2 text-sm leading-relaxed text-ink-2">{t(step.text)}</p>
              </div>
            </BlurFade>
          ))}
        </div>
      </div>
    </section>
  );
}
