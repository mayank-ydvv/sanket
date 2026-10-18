"""Phase 9: baseline, scoring and the benchmark endpoint."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.benchmark_api as benchmark_api
from app.config import Settings
from app.main import create_app
from app.models import Decision, DecisionResult
from scripts.baselines import KeywordTriage
from scripts.benchmark import local_gate_curve, markdown
from scripts.dataset import LabeledReport
from scripts.metrics import evaluate, triage_correct


def row(text: str, emergency: bool, department: str, **extra: object) -> LabeledReport:
    return LabeledReport(
        id="t", text=text, language="en", category="emergency" if emergency else "prank",
        is_emergency=emergency, department=department, severity=4 if emergency else 1,  # type: ignore[arg-type]
        location_text=None, **extra,  # type: ignore[arg-type]
    )


def answer(emergency: bool, department: str, confidence: float = 0.9) -> DecisionResult:
    decision = Decision(
        is_emergency=emergency, emergency_prob=0.9 if emergency else 0.1, department=department,  # type: ignore[arg-type]
        department_conf=confidence, severity=4, alert_now=emergency,
    )
    return DecisionResult(decision=decision, source="local", confidence=confidence, model="test")


def test_keyword_baseline_routes_obvious_reports() -> None:
    triage = KeywordTriage()
    fire, flood, prank = triage.predict_batch(["dukaan mein aag, dhuaan", "बाढ़ का पानी, लोग फंसे हैं", "hello testing"])
    assert fire.decision.department == "fire" and fire.decision.is_emergency
    assert flood.decision.department == "disaster" and flood.decision.severity == 4
    assert not prank.decision.is_emergency and prank.decision.department == "none"


def test_triage_correct_needs_department_only_for_real_emergencies() -> None:
    assert triage_correct(row("x", True, "fire"), answer(True, "fire"))
    assert not triage_correct(row("x", True, "fire"), answer(True, "police"))
    assert triage_correct(row("x", False, "none"), answer(False, "utilities"))


def test_unanswered_reports_are_scored_as_missed() -> None:
    rows = [row("a", True, "fire"), row("b", True, "medical", silent_sos=True)]
    metrics = evaluate(rows, [answer(True, "fire"), None])
    assert metrics["unanswered"] == 1 and metrics["triage_acc"] == 0.5
    assert metrics["emergency"]["recall"] == 0.5 and metrics["silent_sos_caught"] == "0/1"


def test_local_gate_curve() -> None:
    rows = [row("a", True, "fire"), row("b", True, "fire"), row("c", False, "none")]
    answers = [answer(True, "fire", 0.95), answer(True, "police", 0.55), answer(False, "none", 0.75)]
    curve = {c["gate"]: c for c in local_gate_curve(rows, answers)}
    assert curve[0.9]["coverage"] == pytest.approx(1 / 3) and curve[0.9]["triage_acc_on_covered"] == 1.0
    assert curve[0.5]["coverage"] == 1.0 and curve[0.5]["triage_acc_on_covered"] == pytest.approx(2 / 3)


def test_markdown_renders_every_approach() -> None:
    rows = [row("a", True, "fire")]
    summary = {
        "approach": "local only", "triage_acc": 1.0, "triage_acc_hidden50": 0.0,
        "emergency": {"precision": 1.0, "recall": 1.0, "f1": 1.0}, "department_acc": 1.0, "severity_mae": 0.0,
        "silent_sos_caught": "0/0", "unanswered": 0, "per_language": {"en": {"triage_acc": 1.0}},
        "latency_ms": {"median": 1.0, "p95": 2.0}, "llm_calls": 0, "cost_per_1000_inr": 0.0, "notes": [],
    }
    text = markdown({"n": len(rows), "run_at": "now", "approaches": [summary], "notes": [], "local_gate_curve": []})
    assert "| local only | 1.000 |" in text


def test_benchmark_endpoint(settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "benchmark.json"
    monkeypatch.setattr(benchmark_api, "BENCHMARK_PATH", path)
    with TestClient(create_app(settings)) as client:
        assert client.get("/benchmark").status_code == 404
        path.write_text(json.dumps({"n": 1, "approaches": []}))
        assert client.get("/benchmark").json() == {"n": 1, "approaches": []}
