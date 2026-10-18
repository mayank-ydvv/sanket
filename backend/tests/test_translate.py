"""English translations: inside the fast-LLM decision, and on demand when an incident is opened."""

import json
import re
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.config import Settings
from app.decision.llm import FallbackChain, LLMOutcome, LLMStats, ProviderSlot
from app.decision.providers import ProviderReply, RateLimiter
from app.demo import DemoCache, DemoRecorder
from app.main import create_app
from app.translate import Translator, parse_translations
from tests.conftest import receive_event
from tests.test_llm import FakeProvider, make_decider, run_with

_LINE = re.compile(r"^\[(\d+)\] (.*)$", re.MULTILINE)
TAMIL = "முடிச்சூரில் வீடுகளுக்குள் தண்ணீர் புகுந்தது"
ENGLISH = "Water has entered the houses in Mudichur"


def wait_until(condition: Callable[[], bool], timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while not condition():
        assert time.monotonic() < deadline, "condition not met in time"
        time.sleep(0.05)


def fake_english(text: str) -> str:
    return "" if text.isascii() else f"EN: {text[:12]}"


def decisions_with_english(user: str) -> str:
    items = [
        {"i": int(i), "e": True, "p": 0.95, "d": "disaster", "dc": 0.93, "s": 5, "a": True, "en": fake_english(t)}
        for i, t in _LINE.findall(user)
    ]
    return json.dumps({"r": items})


def translations_only(user: str) -> str:
    """Answers translation requests; decision requests get unusable output (LLM 'down')."""
    if '{"t": [...]}' not in user:
        return "not json"
    return json.dumps({"t": [{"i": int(i), "en": fake_english(t)} for i, t in _LINE.findall(user)]})


async def test_fast_llm_decision_carries_the_english_translation() -> None:
    results = await run_with(make_decider(FakeProvider("fake", decisions_with_english)), 4)
    assert all(r.source == "llm" and r.english_gloss == "" for r in results)  # "" = already English


def test_parse_translations_drops_bad_items() -> None:
    reply = '{"t":[{"i":0,"en":"  fire   near\\nthe market "},{"i":0,"en":"dup"},{"i":7,"en":"x"},{"i":"1","en":"y"}]}'
    assert parse_translations(reply, 2) == {0: "fire near the market"}
    assert parse_translations("sorry", 2) == {}


def make_translator(provider: FakeProvider, **kwargs: object) -> Translator:
    chain = FallbackChain([ProviderSlot(provider, RateLimiter(1000, 1e7))], LLMStats(), 1.0)  # type: ignore[arg-type]
    return Translator(chain, **kwargs)  # type: ignore[arg-type]


async def test_translations_are_recorded_and_replayed_offline(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    recorder = DemoRecorder(path)
    live = make_translator(FakeProvider("fake", translations_only), recorder=recorder)
    assert await live.translate([TAMIL, "fire at the market"]) == [fake_english(TAMIL), ""]
    recorder.close()

    stats = LLMStats()
    replay = Translator(FallbackChain([], stats, 0.0), replay=DemoCache.load(path))
    assert replay.available
    assert await replay.translate([TAMIL, "never recorded"]) == [fake_english(TAMIL), None]
    await replay.translate([TAMIL])
    assert stats.calls["fake/fake-model"] == 1  # charged once, like the live call


def test_decision_translation_reaches_the_board(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider("fake", decisions_with_english)
    monkeypatch.setattr(main_module, "build_llm_decider", lambda cfg, http, limiters, recorder=None: make_decider(provider))
    with TestClient(create_app(settings)) as client, client.websocket_connect("/ws") as ws:
        report_id = client.post("/reports", json={"text": TAMIL}).json()["id"]
        incident_id = receive_event(ws, "incident.created")["data"]["id"]

        def report() -> dict:
            return client.get(f"/incidents/{incident_id}").json()["reports"][0]

        wait_until(lambda: report()["english_gloss"] is not None)
        assert report()["id"] == report_id and report()["english_gloss"] == fake_english(TAMIL)


def test_opening_an_incident_translates_its_untranslated_reports_once(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = FakeProvider("fake", translations_only)
    monkeypatch.setattr(main_module, "build_llm_decider", lambda cfg, http, limiters, recorder=None: make_decider(provider))
    with TestClient(create_app(settings)) as client, client.websocket_connect("/ws") as ws:
        client.post("/reports", json={"text": TAMIL})
        incident_id = receive_event(ws, "incident.created")["data"]["id"]
        wait_until(lambda: provider.calls >= 2)  # decision asked twice, unusable: local answer stands
        time.sleep(0.2)
        report = client.get(f"/incidents/{incident_id}").json()["reports"][0]
        assert report["english_gloss"] is None
        calls_before = provider.calls

        first = client.post(f"/incidents/{incident_id}/translate").json()
        assert first == {"translated": 1, "pending": 0, "available": True}
        update = receive_event(ws, "report.updated")["data"]
        assert update["english_gloss"] == fake_english(TAMIL)
        assert client.get(f"/incidents/{incident_id}").json()["reports"][0]["english_gloss"] == fake_english(TAMIL)
        assert client.post(f"/incidents/{incident_id}/translate").json()["translated"] == 0
        assert provider.calls == calls_before + 1
        assert client.post("/incidents/i_missing/translate").status_code == 404


def test_translation_without_any_provider_reports_unavailable(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        client.post("/reports", json={"text": TAMIL})
        incident_id = receive_event(ws, "incident.created")["data"]["id"]
    assert client.post(f"/incidents/{incident_id}/translate").json() == {
        "translated": 0,
        "pending": 1,
        "available": False,
    }


def test_replayed_decision_keeps_its_translation(tmp_path: Path) -> None:
    from app.models import Decision

    path = tmp_path / "run.jsonl"
    recorder = DemoRecorder(path)
    decision = Decision(is_emergency=True, emergency_prob=0.9, department="disaster", department_conf=0.9, severity=5, alert_now=True)
    recorder.decision(TAMIL, LLMOutcome(decision, "groq", "qwen", ENGLISH), ProviderReply("", "groq", "qwen", 10, 10, 0.1), 1)
    recorder.close()
    assert DemoCache.load(path).decisions[TAMIL].english == ENGLISH
