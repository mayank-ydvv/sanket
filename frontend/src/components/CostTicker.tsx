import { formatInr } from "../lib/store";
import type { CostSnapshot } from "../types";

export function CostTicker({ cost }: { cost: CostSnapshot | null }) {
  if (!cost) return null;
  return (
    <div
      className="flex items-center gap-4 rounded-lg border border-line bg-panel px-3 py-1.5"
      title={`At listed per-token prices (billed today: ${formatInr(cost.billed_inr)} on free tiers). ${cost.llm_calls} LLM calls, ${cost.input_tokens.toLocaleString()} in / ${cost.output_tokens.toLocaleString()} out tokens for ${cost.reports} reports.`}
    >
      <div className="leading-tight">
        <p className="font-mono text-sm font-semibold text-emerald-300">{formatInr(cost.sanket_inr)}</p>
        <p className="text-[10px] uppercase tracking-wider text-mute">Sanket</p>
      </div>
      <span className="text-mute">vs</span>
      <div className="leading-tight">
        <p className="font-mono text-sm font-semibold text-rose-300">{formatInr(cost.counterfactual_inr)}</p>
        <p className="text-[10px] uppercase tracking-wider text-mute">all to large LLM</p>
      </div>
      {cost.counterfactual_inr > 0 && (
        <p className="font-mono text-xs text-ink">
          {cost.saved_pct.toFixed(1)}% <span className="text-mute">less</span>
        </p>
      )}
    </div>
  );
}
