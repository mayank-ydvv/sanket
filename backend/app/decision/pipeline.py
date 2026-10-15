"""System 1 decision pipeline: local classifier -> fast LLM (uncertain only) -> safety rules."""

import asyncio
from collections.abc import Sequence

from app.decision.llm import LLMDecider, LLMOutcome
from app.decision.local import LocalClassifier
from app.decision.rules import SafetyRules
from app.models import Decision, DecisionResult, Report

UNTRIAGED = DecisionResult(
    decision=Decision(
        is_emergency=True,
        emergency_prob=0.5,
        department="none",
        department_conf=0.5,
        severity=3,
        alert_now=False,
        needs_human_review=True,
    ),
    source="local",
    confidence=0.5,
    model="untriaged",
)
OVERRIDING_RULES = ("silent_sos", "severity_floor")


def _from_llm(outcome: LLMOutcome, prompt_version: str) -> DecisionResult:
    return DecisionResult(
        decision=outcome.decision,
        source="llm",
        confidence=outcome.decision.confidence,
        model=f"{outcome.provider}/{outcome.model}",
        prompt_version=prompt_version,
    )


def _needs_review(result: DecisionResult) -> DecisionResult:
    """Local answer kept after an LLM failure: flagged for a human, never dropped."""
    decision = result.decision.model_copy(update={"needs_human_review": True})
    return result.model_copy(update={"decision": decision})


class DecisionPipeline:
    """Every report: local first; below ``conf_threshold`` the fast LLM; rules always last.

    Without a trained model every report is marked for review. Without any LLM
    provider configured, uncertain local answers stand and the confidence gates
    route them to one-click confirm or review.
    """

    def __init__(
        self,
        local: LocalClassifier | None,
        llm: LLMDecider | None,
        rules: SafetyRules,
        conf_threshold: float,
    ) -> None:
        self._local = local
        self._llm = llm
        self._rules = rules
        self._threshold = conf_threshold

    async def decide_batch(self, reports: Sequence[Report]) -> list[DecisionResult]:
        """One decision per report, in order.

        O(b·L) local work in a worker thread; uncertain items share LLM calls
        with other in-flight batches; rules are O(L) per report.
        """
        texts = [r.raw_text for r in reports]
        if self._local is None:
            results = [UNTRIAGED for _ in reports]
        else:
            results = await asyncio.to_thread(self._local.predict_batch, texts)

        uncertain = [i for i, r in enumerate(results) if r.confidence < self._threshold]
        if self._llm is not None and uncertain:
            outcomes = await self._llm.decide([texts[i] for i in uncertain])
            for i, outcome in zip(uncertain, outcomes, strict=True):
                results[i] = (
                    _from_llm(outcome, self._llm.prompt_version)
                    if outcome is not None
                    else _needs_review(results[i])
                )

        return [self._apply_rules(report, result) for report, result in zip(reports, results, strict=True)]

    def _apply_rules(self, report: Report, result: DecisionResult) -> DecisionResult:
        outcome = self._rules.apply(report.raw_text, report.channel, report.caller_hash, result.decision)
        overridden = any(f.startswith(OVERRIDING_RULES) for f in outcome.fired)
        return result.model_copy(
            update={
                "decision": outcome.decision,
                "rules_fired": outcome.fired,
                "source": "rules" if overridden else result.source,
                "confidence": outcome.decision.confidence,
            }
        )
