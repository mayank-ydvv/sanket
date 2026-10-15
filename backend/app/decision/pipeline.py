"""Decision pipeline: turns a batch of reports into triage decisions."""

from collections.abc import Sequence

from app.models import Decision, DecisionResult, Report

_UNTRIAGED = DecisionResult(
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


async def decide_batch(reports: Sequence[Report]) -> list[DecisionResult]:
    """Return one decision per report, in order. O(b).

    Until the classifier exists every report is treated as a possible
    emergency and sent to human review: never dismissed, never auto-dispatched.
    """
    return [_UNTRIAGED for _ in reports]
