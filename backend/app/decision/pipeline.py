"""System 1 decision pipeline: local classifier + rules now; fast LLM revises uncertain ones.

``decide_fast`` answers every report at once from the local model, so it reaches
the board immediately. Reports below ``conf_threshold`` are then ``refine``d by the
fast LLM in the background and revised in place. ``decide_batch`` chains both for
callers that want the final answer directly (tests, benchmark).
"""

import asyncio
from collections.abc import Sequence

from app.decision.llm import Decider
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


class DecisionPipeline:
    """Without a trained model every report is marked for review. Without any LLM
    provider, uncertain local answers stand and the confidence gates route them
    to one-click confirm or review."""

    def __init__(
        self,
        local: LocalClassifier | None,
        llm: Decider | None,
        rules: SafetyRules,
        conf_threshold: float,
    ) -> None:
        self._local = local
        self._llm = llm
        self._rules = rules
        self._threshold = conf_threshold

    def wants_llm(self, result: DecisionResult) -> bool:
        """True when the fast LLM should revise this decision. Silent SOS stays with rules."""
        return (
            self._llm is not None
            and result.confidence < self._threshold
            and not result.decision.silent_sos
        )

    async def decide_fast(self, reports: Sequence[Report]) -> list[DecisionResult]:
        """Local model + rules for a batch. O(b·L), model work in a worker thread."""
        texts = [r.raw_text for r in reports]
        if self._local is None:
            results = [UNTRIAGED for _ in reports]
        else:
            results = await asyncio.to_thread(self._local.predict_batch, texts)
        return [self._apply_rules(rep, res) for rep, res in zip(reports, results, strict=True)]

    async def refine(
        self, reports: Sequence[Report], fast: Sequence[DecisionResult]
    ) -> list[DecisionResult]:
        """LLM answers for uncertain reports, re-checked by the rules.

        Items the LLM could not answer keep their local decision, flagged for review.
        Shares LLM calls with every other in-flight batch (see LLMDecider).
        """
        assert self._llm is not None
        outcomes = await self._llm.decide([r.raw_text for r in reports])
        revised: list[DecisionResult] = []
        for report, prior, outcome in zip(reports, fast, outcomes, strict=True):
            if outcome is None:
                decision = prior.decision.model_copy(update={"needs_human_review": True})
                revised.append(prior.model_copy(update={"decision": decision}))
                continue
            result = DecisionResult(
                decision=outcome.decision,
                source="llm",
                confidence=outcome.decision.confidence,
                model=f"{outcome.provider}/{outcome.model}",
                prompt_version=self._llm.prompt_version,
                english_gloss=outcome.english,
            )
            revised.append(self._apply_rules(report, result, prior_prank=prior.decision.prank_score))
        return revised

    async def decide_batch(self, reports: Sequence[Report]) -> list[DecisionResult]:
        """Final decisions in one call: fast pass, then LLM revision of uncertain items."""
        results = await self.decide_fast(reports)
        uncertain = [i for i, r in enumerate(results) if self.wants_llm(r)]
        if uncertain:
            revised = await self.refine([reports[i] for i in uncertain], [results[i] for i in uncertain])
            for i, result in zip(uncertain, revised, strict=True):
                results[i] = result
        return results

    def _apply_rules(
        self, report: Report, result: DecisionResult, prior_prank: float | None = None
    ) -> DecisionResult:
        outcome = self._rules.apply(
            report.raw_text, report.channel, report.caller_hash, result.decision, prior_prank
        )
        overridden = any(f.startswith(OVERRIDING_RULES) for f in outcome.fired)
        return result.model_copy(
            update={
                "decision": outcome.decision,
                "rules_fired": outcome.fired,
                "source": "rules" if overridden else result.source,
                "confidence": outcome.decision.confidence,
            }
        )
