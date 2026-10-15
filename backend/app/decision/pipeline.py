"""Decision pipeline: turns a batch of reports into triage decisions."""

import asyncio
from collections.abc import Sequence

from app.decision.local import LocalClassifier
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
    source="rules",
    confidence=0.5,
)


class DecisionPipeline:
    """System 1 decisions. Without a trained model every report goes to human review."""

    def __init__(self, local: LocalClassifier | None) -> None:
        self._local = local

    async def decide_batch(self, reports: Sequence[Report]) -> list[DecisionResult]:
        """One decision per report, in order. O(b·L), run off the event loop."""
        if self._local is None:
            return [UNTRIAGED for _ in reports]
        return await asyncio.to_thread(self._local.predict_batch, [r.raw_text for r in reports])
