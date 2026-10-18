"""Triage metrics shared by training and the benchmark."""

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

from app.models import Decision, DecisionResult
from scripts.dataset import LabeledReport

# An approach that produced no answer for a report (LLM unavailable) is scored as
# "not an emergency, no department": the worst safe-looking outcome.
NO_ANSWER = DecisionResult(
    decision=Decision(
        is_emergency=False, emergency_prob=0.0, department="none", department_conf=0.0, severity=1, alert_now=False
    ),
    source="local",
    confidence=0.0,
    model="no-answer",
)


def triage_correct(row: LabeledReport, result: DecisionResult) -> bool:
    """Emergency call right and, for real emergencies, the right department."""
    d = result.decision
    return d.is_emergency == row.is_emergency and (not row.is_emergency or d.department == row.department)

DEPARTMENT_ORDER = ("fire", "police", "medical", "disaster", "utilities", "none")


def evaluate(
    rows: Sequence[LabeledReport], answers: Sequence[DecisionResult | None], gate: float = 0.8
) -> dict[str, Any]:
    """Compute every triage metric in one pass plus sklearn summaries. O(n)."""
    results = [a if a is not None else NO_ANSWER for a in answers]
    triage_ok = [triage_correct(r, res) for r, res in zip(rows, results, strict=True)]
    truth_e = [r.is_emergency for r in rows]
    pred_e = [res.decision.is_emergency for res in results]
    precision, recall, f1, _ = precision_recall_fscore_support(
        truth_e, pred_e, average="binary", zero_division=0
    )
    dept_ok = [r.department == res.decision.department for r, res in zip(rows, results, strict=True)]
    per_language: dict[str, dict[str, float]] = {}
    groups: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        groups[row.language].append(i)
    for language, idx in sorted(groups.items()):
        per_language[language] = {
            "n": len(idx),
            "triage_acc": sum(triage_ok[i] for i in idx) / len(idx),
            "emergency_acc": sum(truth_e[i] == pred_e[i] for i in idx) / len(idx),
            "department_acc": sum(dept_ok[i] for i in idx) / len(idx),
        }
    confident = [i for i, res in enumerate(results) if res.confidence >= gate]
    sos = [i for i, row in enumerate(rows) if row.silent_sos]
    return {
        "n": len(rows),
        "unanswered": sum(a is None for a in answers),
        "triage_acc": sum(triage_ok) / len(rows),
        "silent_sos_caught": f"{sum(results[i].decision.silent_sos for i in sos)}/{len(sos)}",
        "emergency": {"precision": precision, "recall": recall, "f1": f1},
        "emergency_acc": sum(t == p for t, p in zip(truth_e, pred_e, strict=True)) / len(rows),
        "department_acc": sum(dept_ok) / len(rows),
        "department_confusion": {
            "labels": list(DEPARTMENT_ORDER),
            "matrix": confusion_matrix(
                [r.department for r in rows],
                [res.decision.department for res in results],
                labels=list(DEPARTMENT_ORDER),
            ).tolist(),
        },
        "severity_mae": sum(abs(r.severity - res.decision.severity) for r, res in zip(rows, results, strict=True))
        / len(rows),
        "per_language": per_language,
        "gate": {
            "threshold": gate,
            "coverage": len(confident) / len(rows),
            "department_acc": (sum(dept_ok[i] for i in confident) / len(confident)) if confident else None,
        },
    }


def format_summary(metrics: dict[str, Any]) -> str:
    e = metrics["emergency"]
    lines = [
        f"emergency  P={e['precision']:.3f} R={e['recall']:.3f} F1={e['f1']:.3f} acc={metrics['emergency_acc']:.3f}",
        f"department acc={metrics['department_acc']:.3f}   severity MAE={metrics['severity_mae']:.2f}",
        "per language:",
        *(
            f"  {lang:9s} n={m['n']:3d} emergency={m['emergency_acc']:.3f} department={m['department_acc']:.3f}"
            for lang, m in metrics["per_language"].items()
        ),
    ]
    gate = metrics["gate"]
    dept = "n/a" if gate["department_acc"] is None else f"{gate['department_acc']:.3f}"
    lines.append(
        f"confidence >= {gate['threshold']}: coverage={gate['coverage']:.2f} department acc={dept}"
    )
    return "\n".join(lines)
