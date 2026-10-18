import { useMemo, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { formatInr } from "@/lib/store";
import { type ApproachResult, HYBRID, latencyLabel } from "./types";

const W = 760;
const H = 400;
const M = { top: 24, right: 150, bottom: 56, left: 56 };
const FREE_BAND = 80; // column for approaches that cost nothing

/**
 * Accuracy (y) vs cost per 1,000 reports (x, log). Five approaches exceed the three
 * colours a scatter keeps distinguishable, so identity is carried by direct labels;
 * only Sanket is highlighted (accent), the rest are neutral.
 */
export function AccuracyCostChart({ data }: { data: ApproachResult[] }) {
  const { t: tr } = useI18n();
  const [hover, setHover] = useState<string | null>(null);
  const paid = data.filter((d) => d.cost_per_1000_inr > 0);
  const minCost = Math.min(...paid.map((d) => d.cost_per_1000_inr), 1) / 2;
  const maxCost = Math.max(...paid.map((d) => d.cost_per_1000_inr), 10) * 2;
  const [logMin, logMax] = [Math.log10(minCost), Math.log10(maxCost)];
  const yMin = Math.max(0, Math.floor(Math.min(...data.map((d) => d.triage_acc)) * 10) / 10 - 0.1);
  const plotLeft = M.left + FREE_BAND;
  const x = (cost: number) =>
    cost <= 0 ? M.left + FREE_BAND / 2 : plotLeft + ((Math.log10(cost) - logMin) / (logMax - logMin)) * (W - M.right - plotLeft);
  const y = (acc: number) => M.top + ((1 - acc) / (1 - yMin)) * (H - M.top - M.bottom);
  const yTicks = useMemo(() => {
    const ticks: number[] = [];
    for (let t = Math.ceil(yMin * 10) / 10; t <= 1.0001; t += 0.1) ticks.push(Math.round(t * 10) / 10);
    return ticks;
  }, [yMin]);
  const xTicks = [0.01, 0.1, 1, 10, 100, 1000].filter((t) => t >= minCost && t <= maxCost);
  const hovered = data.find((d) => d.approach === hover);

  // Direct labels must never collide with a label or a dot. A point with a neighbour
  // just to its right is labelled on its left; other near labels are pushed down. O(n²), n = 5.
  const LABEL_GAP = 16;
  const labelY = new Map<string, number>();
  const labelLeft = new Set<string>();
  const points = data.map((d) => ({ d, cx: x(d.cost_per_1000_inr), cy: y(d.triage_acc) }));
  for (const p of points) {
    if (points.some((q) => q !== p && q.cx > p.cx && q.cx - p.cx < 130 && Math.abs(q.cy - p.cy) < LABEL_GAP)) {
      labelLeft.add(p.d.approach);
    }
  }
  const placed: { x: number; y: number; left: boolean }[] = [];
  for (const { d, cx, cy } of [...points].sort((a, b) => a.cy - b.cy)) {
    const left = labelLeft.has(d.approach);
    let ly = cy;
    for (const p of placed) {
      if (p.left === left && Math.abs(p.x - cx) < 170 && Math.abs(p.y - ly) < LABEL_GAP) ly = p.y + LABEL_GAP;
    }
    placed.push({ x: cx, y: ly, left });
    labelY.set(d.approach, ly);
  }

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={tr("bench.chartLabel")}>
        {yTicks.map((t) => (
          <g key={t}>
            <line x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)} stroke="var(--line)" />
            <text x={M.left - 10} y={y(t)} dy="0.32em" textAnchor="end" fontSize={11} fill="var(--mute)">
              {Math.round(t * 100)}%
            </text>
          </g>
        ))}
        <rect x={M.left} y={M.top} width={FREE_BAND - 12} height={H - M.top - M.bottom} rx={8} fill="var(--surface-2)" />
        <text x={M.left + FREE_BAND / 2 - 6} y={H - M.bottom + 20} textAnchor="middle" fontSize={11} fill="var(--mute)">
          {tr("bench.free")}
        </text>
        {xTicks.map((t) => (
          <text key={t} x={x(t)} y={H - M.bottom + 20} textAnchor="middle" fontSize={11} fill="var(--mute)">
            {t >= 1 ? `₹${t.toLocaleString("en-IN")}` : `₹${t}`}
          </text>
        ))}
        <text x={(plotLeft + W - M.right) / 2} y={H - 12} textAnchor="middle" fontSize={12} fill="var(--mute)">
          {tr("bench.axisX")}
        </text>
        <text transform={`translate(16 ${(M.top + H - M.bottom) / 2}) rotate(-90)`} textAnchor="middle" fontSize={12} fill="var(--mute)">
          {tr("bench.axisY")}
        </text>
        {data.map((d) => {
          const isHybrid = d.approach === HYBRID;
          const cx = x(d.cost_per_1000_inr);
          const cy = y(d.triage_acc);
          return (
            <g
              key={d.approach}
              tabIndex={0}
              className="cursor-default outline-none"
              onMouseEnter={() => setHover(d.approach)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(d.approach)}
              onBlur={() => setHover(null)}
            >
              <circle cx={cx} cy={cy} r={18} fill="transparent" />
              {isHybrid && <circle cx={cx} cy={cy} r={14} fill="var(--accent)" opacity={0.15} />}
              <circle cx={cx} cy={cy} r={isHybrid ? 8 : 6} fill={isHybrid ? "var(--accent)" : "var(--mute)"} stroke="var(--surface)" strokeWidth={2} />
              {labelY.get(d.approach)! - cy > 2 && (
                <line x1={cx + 6} y1={cy + 4} x2={cx + 12} y2={labelY.get(d.approach)!} stroke="var(--line-strong)" />
              )}
              <text
                x={labelLeft.has(d.approach) ? cx - 14 : cx + 14}
                y={labelY.get(d.approach)}
                dy="0.32em"
                textAnchor={labelLeft.has(d.approach) ? "end" : "start"}
                fontSize={12}
                fontWeight={isHybrid ? 700 : 500}
                fill={isHybrid ? "var(--ink)" : "var(--ink-2)"}
              >
                {d.approach}
              </text>
            </g>
          );
        })}
      </svg>
      {hovered && (
        <div
          className="pointer-events-none absolute z-10 w-60 rounded-xl border border-line bg-surface px-3.5 py-2.5 text-xs shadow-card"
          style={{
            left: `${(x(hovered.cost_per_1000_inr) / W) * 100}%`,
            top: `${(y(hovered.triage_acc) / H) * 100}%`,
            transform: "translate(-50%, calc(-100% - 16px))",
          }}
        >
          <p className="font-semibold text-ink">{hovered.approach}</p>
          <p className="mt-1 text-ink-2">
            {tr("bench.tip", { acc: (hovered.triage_acc * 100).toFixed(1), recall: (hovered.emergency.recall * 100).toFixed(0) })}
          </p>
          <p className="text-ink-2">
            {formatInr(hovered.cost_per_1000_inr)} / 1,000 · p95 {latencyLabel(hovered.latency_ms.p95)}
          </p>
        </div>
      )}
    </div>
  );
}
