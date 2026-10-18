"""Phase 10: record the LLM layer during a live run, replay it offline with no network."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.cluster.service import IncidentService
from app.config import Settings
from app.db import Database
from app.decision.llm import FallbackChain, LLMOutcome, LLMStats
from app.decision.providers import ProviderReply
from app.demo import DemoCache, DemoRecorder, ReplayDecider, text_key
from app.main import create_app
from app.models import Decision
from app.reasoning.prompting import ReasoningOutput
from app.reasoning.scheduler import Reasoner, ReasonerConfig
from app.ws import Broadcaster
from tests.conftest import receive_event
from tests.test_incidents import make_index
from tests.test_live import RecordingHub
from tests.test_llm import FakeProvider, make_decider, valid_json
from tests.test_reasoning import ANNA_NAGAR, Clock, ScriptedProvider, located, make_reasoner

FIRE = Decision(
    is_emergency=True, emergency_prob=0.95, department="fire", department_conf=0.9, severity=4, alert_now=True
)
RISK = ReasoningOutput(
    linked_hazards=["smoke", "gas smell"],
    combined_risk="Smoke plus gas smell: possible explosion risk",
    briefing=["Location/access: Anna Nagar 2nd Avenue", "Hazards: smoke, gas smell", "People at risk: not stated"],
)


def reply(latency_s: float = 0.01) -> ProviderReply:
    return ProviderReply("", "groq", "qwen", 1000, 400, latency_s)


def test_recording_round_trips_and_skips_bad_lines(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    recorder = DemoRecorder(path)
    recorder.decision("aag   lagi\nhai", LLMOutcome(FIRE, "groq", "qwen"), reply(), share=4)
    recorder.reasoning("Fire · Anna Nagar 2nd Avenue", RISK.model_copy(update={"merge_suggestions": ["i_old"]}), reply(2.5))
    recorder.close()
    with path.open("a") as f:
        f.write("not json\n" + json.dumps({"kind": "decision", "text": "missing fields"}) + "\n")
    cache = DemoCache.load(path)
    recorded = cache.decisions[text_key("aag lagi hai")]
    assert recorded.decision == FIRE and (recorded.input_tokens, recorded.output_tokens) == (250, 100)
    reasoning = cache.reasoning["Fire · Anna Nagar 2nd Avenue"]
    assert reasoning.output.merge_suggestions == []  # incident ids never carry over to another run
    assert reasoning.output.combined_risk == RISK.combined_risk and reasoning.latency_s == 2.5


def test_missing_recording_loads_empty(tmp_path: Path) -> None:
    cache = DemoCache.load(tmp_path / "nope.jsonl")
    assert cache.decisions == {} and cache.reasoning == {}


async def test_live_decider_records_every_answered_report(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    decider = make_decider(FakeProvider("fake", valid_json))
    recorder = DemoRecorder(path)
    decider._recorder = recorder
    runner = asyncio.create_task(decider.run())
    try:
        await decider.decide(["smoke from tower B", "aag lagi hai"])
    finally:
        runner.cancel()
    recorder.close()
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert sorted(r["text"] for r in lines) == ["aag lagi hai", "smoke from tower B"]
    assert all(r["provider"] == "fake" and r["input_tokens"] == 50 for r in lines)  # 100 tokens over 2 items


async def test_replay_answers_hits_and_leaves_misses_to_the_local_model(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    recorder = DemoRecorder(path)
    one_call = reply()
    recorder.decision("aag lagi hai", LLMOutcome(FIRE, "groq", "qwen"), one_call, share=2)
    recorder.decision("smoke in tower B", LLMOutcome(FIRE, "groq", "qwen"), one_call, share=2)
    recorder.close()
    replay = ReplayDecider(DemoCache.load(path))
    hit, miss = await replay.decide([" aag  lagi hai ", "something never recorded"])
    assert hit is not None and hit.decision == FIRE and miss is None
    assert (replay.hits, replay.misses, replay.stats.fallbacks) == (1, 1, 1)
    await replay.decide(["smoke in tower B", "aag lagi hai"])  # same live call; a repeat is free
    assert replay.stats.calls["groq/qwen"] == 1 and replay.stats.input_tokens["groq/qwen"] == 1000
    assert replay.chain.slots == []


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    database = await Database.open(tmp_path / "demo.db")
    yield database  # type: ignore[misc]
    await database.close()


async def test_reasoning_is_recorded_then_replayed_without_a_provider(db: Database, tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    service = IncidentService(db, make_index())
    incident = await located(db, service, "smoke on the 5th floor of tower B", ANNA_NAGAR, seed=1, n=3)
    answer = RISK.model_dump()
    live = make_reasoner(service, db, ScriptedProvider(lambda _user: json.dumps(answer)), Clock())
    recorder = DemoRecorder(path)
    live._recorder = recorder
    assert await live.reason(incident.id) is not None
    recorder.close()

    stats = LLMStats()
    replayer = Reasoner(
        service,
        db,
        FallbackChain([], stats, 0.0),
        Broadcaster(RecordingHub()),  # type: ignore[arg-type]
        ReasonerConfig(),
        replay=DemoCache.load(path),
    )
    await service.apply_reasoning(
        incident.id, risk_hazards=[], combined_risk=None, merge_suggestions=[], briefing=[], actor="t", prompt_version="x"
    )
    replayed = await replayer.reason(incident.id)
    assert replayed is not None and replayed.combined_risk == RISK.combined_risk and replayed.briefing == RISK.briefing
    assert stats.calls["fake/reasoner"] == 1 and stats.output_tokens["fake/reasoner"] == 120
    audit = [a for a in await db.audit_for("incident", incident.id) if a.action == "reasoned"]
    assert audit[-1].actor == "fake/reasoner (demo replay)"
    assert await replayer.reason(incident.id) is None  # answered once: re-runs don't re-charge the ticker
    assert stats.calls["fake/reasoner"] == 1

    other = await located(db, service, "gas smell near the lift", ANNA_NAGAR, seed=2, n=3)
    if other.title != incident.title:
        assert await replayer.reason(other.id) is None  # nothing recorded: no answer, no error


def no_network(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"demo replay made a network call to {request.url}")


def test_demo_cache_app_replays_with_no_network(settings: Settings, tmp_path: Path) -> None:
    text = "Marina beach pe kuch ho gaya, jaldi aao"
    path = tmp_path / "run.jsonl"
    recorder = DemoRecorder(path)
    recorder.decision(text, LLMOutcome(FIRE, "groq", "qwen"), reply(0.3), share=1)  # local answer shows first
    recorder.close()
    cfg = settings.model_copy(
        update={"demo_cache": True, "demo_run_path": path, "geocode_network": True, "gemini_api_key": "unused"}
    )
    app = create_app(cfg, transport=httpx.MockTransport(no_network))
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        assert client.get("/health").json()["mode"] == "demo-replay"
        report_id = client.post("/reports", json={"text": text}).json()["id"]
        assert receive_event(ws, "report.created")["data"]["source"] == "local"
        revised = receive_event(ws, "report.updated")["data"]
        assert revised["id"] == report_id and revised["source"] == "llm" and revised["decision"]["department"] == "fire"
        stats = client.get("/stats").json()
        assert stats["mode"] == "demo-replay" and stats["llm_chain"] == []
        assert stats["cost"]["input_tokens"] == 1000


async def test_seed_backs_up_old_db_and_creates_a_working_demo_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.auth import verify_password
    from scripts import seed_demo

    monkeypatch.setattr(seed_demo, "BACKUP_DIR", tmp_path / "backups")
    db_path = tmp_path / "sanket.db"
    old = await Database.open(db_path)
    await old.close()
    assert seed_demo.back_up(tmp_path / "absent.db") is None
    backup = seed_demo.back_up(db_path)
    assert backup is not None and backup.exists() and not db_path.exists()

    await seed_demo.seed(db_path, "Demo dispatcher", "Demo@Sanket.local", "correct horse")
    fresh = await Database.open(db_path)
    try:
        row = await fresh.user_by_email("demo@sanket.local")
        assert row is not None and verify_password("correct horse", row["password_hash"])
        assert await fresh.incidents(None, 10) == []
    finally:
        await fresh.close()
