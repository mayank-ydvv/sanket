"""Phase 8: System 2 reasoning — triggers, debounce, grounding, merge suggestions."""

import asyncio
import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.cluster.embed import HashingEmbedder
from app.cluster.geocode import GeoPoint
from app.cluster.service import IncidentService, Placed
from app.config import Settings
from app.db import Database
from app.decision.llm import FallbackChain, LLMStats, ProviderSlot
from app.decision.providers import ProviderError, ProviderReply, RateLimiter
from app.main import create_app
from app.models import Incident
from app.reasoning.prompting import parse_reasoning
from app.reasoning.scheduler import Reasoner, ReasonerConfig
from app.ws import Broadcaster
from tests.conftest import receive_event
from tests.test_incidents import make_index, placed
from tests.test_live import RecordingHub

GAUR_CITY = GeoPoint(28.6154, 77.4300, "gazetteer")
NEXT_DOOR = GeoPoint(28.6163, 77.4300, "gazetteer")  # ~100 m north


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class ScriptedProvider:
    """Reasoning model double: records the prompt, answers from a callback."""

    name = "fake"
    model = "reasoner"

    def __init__(self, answer) -> None:  # type: ignore[no-untyped-def]
        self.answer = answer
        self.prompts: list[str] = []

    async def complete(self, system: str, user: str, max_output_tokens: int) -> ProviderReply:
        self.prompts.append(user)
        result = self.answer(user)
        if isinstance(result, Exception):
            raise result
        return ProviderReply(result, self.name, self.model, 500, 120, 0.01)


def unit(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).normal(size=64).astype(np.float32)
    return v / np.linalg.norm(v)


async def located(db: Database, service: IncidentService, text: str, point: GeoPoint, seed: int, n: int = 1) -> Incident:
    items = await placed(db, HashingEmbedder(), [text] * n, department="fire", severity=4, point=point, location="Gaur City 2")
    items = [Placed(i.report, i.result, unit(seed), i.location_text, i.point) for i in items]
    out = await service.assign(items)
    return (out.created or out.updated)[0]


def make_reasoner(service: IncidentService, db: Database, provider: ScriptedProvider, clock: Clock) -> Reasoner:
    chain = FallbackChain([ProviderSlot(provider, RateLimiter(1000, 1e7))], LLMStats(), 1.0)  # type: ignore[arg-type]
    return Reasoner(service, db, chain, Broadcaster(RecordingHub()), ReasonerConfig(), clock=clock)  # type: ignore[arg-type]


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    database = await Database.open(tmp_path / "reasoning.db")
    yield database  # type: ignore[misc]
    await database.close()


def test_parse_reasoning_grounds_and_caps_output() -> None:
    reply = json.dumps(
        {
            "linked_hazards": ["Smoke", "gas smell", "smoke"],
            "combined_risk": "Smoke plus gas smell: possible gas explosion risk",
            "merge_suggestions": ["i_real", "i_invented"],
            "briefing": ["Location/access: Gaur City 2, tower B", "Hazards: smoke, gas smell", "People at risk: not stated", "extra line"],
            "reasoning": "ignored field",
        }
    )
    out = parse_reasoning(f"```json\n{reply}\n```", allowed_merge_ids={"i_real"})
    assert out is not None
    assert out.linked_hazards == ["smoke", "gas smell"]
    assert out.merge_suggestions == ["i_real"]  # ids the model was not shown are dropped
    assert len(out.briefing) == 3
    assert parse_reasoning('{"combined_risk": "none", "briefing": []}', set()).combined_risk is None  # type: ignore[union-attr]
    assert parse_reasoning("I think it is a fire.", set()) is None


async def test_trigger_rules(db: Database) -> None:
    clock = Clock()
    service = IncidentService(db, make_index())
    reasoner = make_reasoner(service, db, ScriptedProvider(lambda u: "{}"), clock)
    lone = await located(db, service, "smoke from a shop", GeoPoint(28.55, 77.30, "gazetteer"), seed=1)
    assert not reasoner.qualifies(lone)  # one report, one hazard, nobody nearby
    busy = await located(db, service, "building on fire", GeoPoint(28.50, 77.40, "gazetteer"), seed=2, n=3)
    assert reasoner.qualifies(busy)  # >= 3 reports
    mixed = await located(db, service, "smoke and a gas smell", GeoPoint(28.45, 77.45, "gazetteer"), seed=3)
    assert reasoner.qualifies(mixed)  # two hazards
    first = await located(db, service, "smoke on the 5th floor", GAUR_CITY, seed=4)
    neighbour = await located(db, service, "fire upstairs", NEXT_DOOR, seed=5)
    assert first.id != neighbour.id and reasoner.qualifies(first)  # another incident within 300 m
    assert not reasoner.qualifies(busy.model_copy(update={"silent_sos": True}))
    assert not reasoner.qualifies(busy.model_copy(update={"severity": 2}))


async def test_debounce_runs_at_most_every_20_seconds_and_only_on_change(db: Database) -> None:
    clock = Clock()
    service = IncidentService(db, make_index())
    reply = json.dumps({"linked_hazards": ["fire"], "combined_risk": None, "merge_suggestions": [], "briefing": ["a", "b", "c"]})
    provider = ScriptedProvider(lambda u: reply)
    reasoner = make_reasoner(service, db, provider, clock)
    incident = await located(db, service, "building on fire", GAUR_CITY, seed=1, n=3)
    reasoner.consider([incident])
    reasoner.consider([incident])  # already pending: ignored
    assert reasoner.due() == [incident.id]
    await reasoner.reason(incident.id)
    reasoner.consider([incident])
    assert reasoner.stats.skipped_unchanged == 1 and reasoner.due() == []  # nothing changed
    grown = await located(db, service, "building on fire", GAUR_CITY, seed=1)
    assert grown.id == incident.id and grown.report_count == 4
    clock.now += 5
    reasoner.consider([grown])
    assert reasoner.due() == []  # changed, but only 5 s since the last run
    clock.now += 15
    assert reasoner.due() == [incident.id]
    assert len(provider.prompts) == 1


async def test_cross_incident_reasoning_links_hazards_and_suggests_merge(db: Database) -> None:
    clock = Clock()
    service = IncidentService(db, make_index())
    smoke = await located(db, service, "smoke on the 5th floor of tower B", GAUR_CITY, seed=1, n=3)
    gas = await located(db, service, "gas smell near the lift", NEXT_DOOR, seed=2)

    def answer(user: str) -> str:
        return json.dumps(
            {
                "linked_hazards": ["smoke", "gas smell"],
                "combined_risk": "Smoke plus a gas smell near the lift: possible gas explosion risk",
                "merge_suggestions": [gas.id, "i_hallucinated"],
                "briefing": [
                    "Location/access: Gaur City 2, tower B, 5th floor",
                    "Hazards: smoke, gas smell near the lift",
                    "People at risk: not stated",
                ],
            }
        )

    provider = ScriptedProvider(answer)
    reasoner = make_reasoner(service, db, provider, clock)
    updated = await reasoner.reason(smoke.id)
    assert updated is not None
    prompt = provider.prompts[0]
    assert gas.id in prompt and "gas smell near the lift" in prompt and "NEARBY INCIDENTS (within 300 m" in prompt
    assert updated.combined_risk and "explosion" in updated.combined_risk
    assert updated.merge_suggestions == [gas.id]
    assert updated.briefing and len(updated.briefing) == 3 and updated.risk_hazards == ["smoke", "gas smell"]
    audit = [a for a in await db.audit_for("incident", smoke.id) if a.action == "reasoned"]
    assert audit and audit[0].actor == "fake/reasoner" and "reasoning_v1" in (audit[0].after or "")
    merged, kept = await service.merge_into(gas.id, smoke.id, actor="dispatcher")
    assert merged.status == "merged" and kept.report_count == 4 and kept.merge_suggestions == []


async def test_failed_reasoning_leaves_incident_unchanged_and_retries_later(db: Database) -> None:
    clock = Clock()
    service = IncidentService(db, make_index())
    reasoner = make_reasoner(service, db, ScriptedProvider(lambda u: ProviderError("fake", "HTTP 503", retryable=True)), clock)
    incident = await located(db, service, "building on fire", GAUR_CITY, seed=1, n=3)
    assert await reasoner.reason(incident.id) is None
    assert (await service.current(incident.id)).briefing is None
    assert reasoner.stats.deferred == 1 and reasoner.stats.failed == 0
    clock.now += 21
    assert reasoner.due() == [incident.id]  # first retry after the debounce (20 s)
    await reasoner.reason(incident.id)
    clock.now += 21
    assert reasoner.due() == []  # backoff doubled to 40 s
    clock.now += 20
    assert reasoner.due() == [incident.id]


async def test_most_severe_incidents_are_reasoned_first(db: Database) -> None:
    clock = Clock()
    service = IncidentService(db, make_index())
    reasoner = make_reasoner(service, db, ScriptedProvider(lambda u: "{}"), clock)
    small = await located(db, service, "building on fire", GeoPoint(28.50, 77.40, "gazetteer"), seed=1, n=3)
    big = await located(db, service, "building on fire", GeoPoint(28.45, 77.45, "gazetteer"), seed=2, n=6)
    reasoner.consider([small, big])
    assert reasoner.due() == [big.id, small.id]


async def test_reasoning_never_blocks_intake(db: Database) -> None:
    clock = Clock()
    service = IncidentService(db, make_index())
    gate = asyncio.Event()

    class Hanging(ScriptedProvider):
        async def complete(self, system: str, user: str, max_output_tokens: int) -> ProviderReply:
            await gate.wait()
            return ProviderReply("{}", self.name, self.model, 1, 1, 0.0)

    reasoner = make_reasoner(service, db, Hanging(lambda u: "{}"), clock)
    runner = asyncio.create_task(reasoner.run())
    incident = await located(db, service, "building on fire", GAUR_CITY, seed=1, n=3)
    reasoner.consider([incident])
    await asyncio.sleep(0.05)  # the reasoning call is now hanging
    more = await asyncio.wait_for(located(db, service, "building on fire", GAUR_CITY, seed=1), timeout=2)
    assert more.report_count == 4
    gate.set()
    runner.cancel()


def test_merge_endpoint(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client, client.websocket_connect("/ws") as ws:
        client.post("/reports", json={"text": "Sector 18 metro pe building mein aag lagi hai"})
        a = receive_event(ws, "report.created")["data"]["incident_id"]
        client.post("/reports", json={"text": "two men fighting with knives at Kalindi Kunj bridge"})
        b = receive_event(ws, "report.created")["data"]["incident_id"]
        assert a != b
        response = client.post(f"/incidents/{b}/merge", json={"into": a})
        assert response.status_code == 200 and response.json()["kept"]["report_count"] == 2
        assert client.post(f"/incidents/{b}/merge", json={"into": a}).status_code == 409
        assert client.post(f"/incidents/{a}/merge", json={"into": a}).status_code == 409
        assert client.post("/incidents/nope/merge", json={"into": a}).status_code == 404
