"""Cost meter: what Sanket's LLM use costs vs sending every report to a large reasoning model.

Sanket's cost uses the token counts the providers return (usage fields), per
model, at listed per-million-token prices. The counterfactual prices every
decided report as its own call to a large reasoning model with the full prompt
(no batching, no local model). Free tiers bill ₹0; both figures are at list
price so the comparison means something at production scale.
"""

import asyncio
import time
from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel

from app.decision.llm import LLMStats
from app.models import Price
from app.ws import Broadcaster

PUBLISH_INTERVAL_S = 0.5  # at most 2 updates per second


class CostSnapshot(BaseModel):
    id: str = "cost"
    reports: int
    llm_calls: int
    input_tokens: int
    output_tokens: int
    sanket_inr: float
    counterfactual_inr: float
    saved_pct: float
    sanket_per_1000_inr: float
    counterfactual_per_1000_inr: float
    billed_inr: float = 0.0  # free tiers


class CostMeter:
    def __init__(
        self,
        stats: Sequence[LLMStats],
        prices: dict[str, Price],
        counterfactual_price: Price,
        counterfactual_tokens: tuple[int, int],
        usd_to_inr: float,
        reports: Callable[[], int],
        broadcaster: Broadcaster,
    ) -> None:
        self._stats = stats
        self._prices = prices
        self._cf_price = counterfactual_price
        self._cf_tokens = counterfactual_tokens
        self._usd_to_inr = usd_to_inr
        self._reports = reports
        self._broadcaster = broadcaster
        self._last: dict[str, Any] | None = None

    def _price_for(self, provider_model: str) -> Price:
        """Stats keys are 'provider/model'; prices are keyed by model. O(1)."""
        model = provider_model.split("/", 1)[-1]
        return self._prices.get(model) or self._prices.get(provider_model) or Price(input=0.0, output=0.0)

    def snapshot(self) -> CostSnapshot:
        """O(m) over the models used."""
        inputs: Counter[str] = Counter()
        outputs: Counter[str] = Counter()
        calls = 0
        for stats in self._stats:  # System 1 fast path and System 2 reasoning
            inputs.update(stats.input_tokens)
            outputs.update(stats.output_tokens)
            calls += sum(stats.calls.values())
        usd = sum(
            inputs.get(key, 0) * self._price_for(key).input + outputs.get(key, 0) * self._price_for(key).output
            for key in set(inputs) | set(outputs)
        ) / 1e6
        reports = self._reports()
        cf_in, cf_out = self._cf_tokens
        cf_usd = reports * (cf_in * self._cf_price.input + cf_out * self._cf_price.output) / 1e6
        sanket, counterfactual = usd * self._usd_to_inr, cf_usd * self._usd_to_inr
        per_1000 = 1000 / reports if reports else 0.0
        return CostSnapshot(
            reports=reports,
            llm_calls=calls,
            input_tokens=sum(inputs.values()),
            output_tokens=sum(outputs.values()),
            sanket_inr=round(sanket, 4),
            counterfactual_inr=round(counterfactual, 2),
            saved_pct=round(100 * (1 - sanket / counterfactual), 2) if counterfactual else 0.0,
            sanket_per_1000_inr=round(sanket * per_1000, 4),
            counterfactual_per_1000_inr=round(counterfactual * per_1000, 2),
        )

    def publish_if_changed(self) -> bool:
        data = self.snapshot().model_dump()
        if data == self._last:
            return False
        self._last = data
        self._broadcaster.publish("cost.updated", data)
        return True

    async def run(self, interval_s: float = PUBLISH_INTERVAL_S) -> None:
        """Publish at most once per ``interval_s`` and only when something changed."""
        while True:
            started = time.monotonic()
            self.publish_if_changed()
            await asyncio.sleep(max(0.0, interval_s - (time.monotonic() - started)))
