"""Phase 7: disaster-mode generator and runner, cost meter."""

import asyncio
import time
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.corpus import EVENTS
from app.cost import CostMeter
from app.decision.llm import LLMStats
from app.main import create_app
from app.models import Price
from app.simulate import FLOOD_EVENTS, generate
from app.ws import Broadcaster


def test_flood_surge_has_every_ingredient() -> None:
    reports = generate("flood", 500)
    assert len(reports) == 500 and generate("flood", 500) == reports  # deterministic
    kinds = Counter(r.kind for r in reports)
    assert kinds["silent_sos"] == 2 and kinds["prank"] >= 6 and kinds["non_urgent"] > 0
    assert {r.event for r in reports if r.event is not None} == set(range(len(FLOOD_EVENTS)))
    assert len({r.caller for r in reports}) < 500  # people call back about the same event
    prank = [r for r in reports if r.caller == "+919888800000"]
    assert len(prank) == 6  # one prank caller, contradicting departments
    gas_event = next(i for i, e in enumerate(FLOOD_EVENTS) if e.phrasings == (5, 1))
    texts = " ".join(r.text.lower() for r in reports if r.event == gas_event)
    assert "gas" in texts and ("floor" in texts or "manzil" in texts or "मंजिल" in texts)
    assert any(EVENTS["ta"]["disaster"][0].text[:6] in r.text for r in reports)  # Tamil present


def wait_for(client: TestClient, predicate: Any, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get("/simulate/status").json()
        if predicate(status):
            return status
        time.sleep(0.1)
    raise AssertionError(f"simulation did not finish: {client.get('/simulate/status').json()}")


def test_disaster_endpoint_streams_reports_through_the_pipeline(settings: Settings, model_path: Path) -> None:
    app = create_app(settings.model_copy(update={"local_model_path": model_path}))
    with TestClient(app) as client:
        started = client.post("/simulate/disaster", params={"n": 120, "seconds": 1})
        assert started.status_code == 202 and started.json()["total"] == 120
        assert client.post("/simulate/disaster", params={"n": 50, "seconds": 1}).status_code == 409
        status = wait_for(client, lambda s: not s["running"], timeout=20)
        assert status["decided"] == 120 and status["decided_s"] is not None
        incidents = client.get("/incidents", params={"limit": 500}).json()
        assert sum(i["report_count"] for i in incidents) == 120


def test_500_report_surge_is_triaged_within_15_seconds(settings: Settings, model_path: Path) -> None:
    """Non-functional target (no LLM in tests): 500 reports in 10 s, all decided by 15 s."""
    app = create_app(settings.model_copy(update={"local_model_path": model_path}))
    with TestClient(app) as client:
        client.post("/simulate/disaster", params={"n": 500, "seconds": 10})
        status = wait_for(client, lambda s: not s["running"], timeout=30)
    print(f"\n500 reports: submitted in {status['submitted_s']:.1f}s, decided in {status['decided_s']:.1f}s")
    assert status["decided"] == 500 and status["decided_s"] <= 15


class FakeBroadcaster:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def publish(self, event: str, data: dict[str, Any]) -> None:
        self.events.append((event, data))


def meter(stats: LLMStats, reports: list[int], broadcaster: Any) -> CostMeter:
    return CostMeter(
        [stats],
        {"qwen-test": Price(input=0.3, output=0.6)},
        Price(input=2.5, output=15.0),
        (1500, 500),
        84.0,
        lambda: reports[0],
        broadcaster,
    )


def test_cost_uses_real_tokens_and_counterfactual() -> None:
    stats = LLMStats()
    stats.calls["groq/qwen-test"] = 4
    stats.input_tokens["groq/qwen-test"] = 10_000
    stats.output_tokens["groq/qwen-test"] = 2_000
    snap = meter(stats, [500], FakeBroadcaster()).snapshot()
    # Sanket: (10k * 0.3 + 2k * 0.6) / 1e6 USD * 84
    assert snap.sanket_inr == round((10_000 * 0.3 + 2_000 * 0.6) / 1e6 * 84, 4)
    # Counterfactual: 500 reports * (1500 * 2.5 + 500 * 15) / 1e6 USD * 84
    assert snap.counterfactual_inr == round(500 * (1500 * 2.5 + 500 * 15) / 1e6 * 84, 2)
    assert snap.saved_pct > 99 and snap.llm_calls == 4 and snap.billed_inr == 0.0
    assert snap.counterfactual_per_1000_inr == round(snap.counterfactual_inr * 2, 2)


async def test_cost_updates_publish_at_most_twice_per_second() -> None:
    stats, reports, broadcaster = LLMStats(), [0], FakeBroadcaster()
    cost = meter(stats, reports, broadcaster)
    runner = asyncio.create_task(cost.run(interval_s=0.5))
    for _ in range(40):  # reports change every 25 ms for 1 s
        reports[0] += 10
        await asyncio.sleep(0.025)
    runner.cancel()
    assert 1 <= len(broadcaster.events) <= 3
    assert cost.publish_if_changed() and not cost.publish_if_changed()  # unchanged -> silent
