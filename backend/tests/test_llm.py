import asyncio
import json
import re
from collections.abc import Callable

import pytest

from app.decision.llm import FallbackChain, LLMDecider, LLMStats, ProviderSlot
from app.decision.pipeline import DecisionPipeline
from app.decision.providers import ProviderError, ProviderReply, RateLimiter
from app.decision.rules import PrankTracker, SafetyRules
from app.models import Report

_LINE = re.compile(r"^\[(\d+)\] (.*)$", re.MULTILINE)


def valid_json(user: str) -> str:
    items = [
        {
            "idx": int(i),
            "is_emergency": True,
            "emergency_prob": 0.95,
            "department": "fire",
            "department_conf": 0.93,
            "severity": 4,
            "alert_now": True,
            "hazards": ["smoke"],
        }
        for i, _ in _LINE.findall(user)
    ]
    return json.dumps({"results": items})


class FakeProvider:
    def __init__(self, name: str, respond: Callable[[str], str] | Exception) -> None:
        self.name = name
        self.model = f"{name}-model"
        self.calls = 0
        self._respond = respond

    async def complete(self, system: str, user: str) -> ProviderReply:
        self.calls += 1
        if isinstance(self._respond, Exception):
            raise self._respond
        return ProviderReply(self._respond(user), self.name, self.model, 100, 50, 0.01)


def make_decider(*providers: FakeProvider, batch_wait_s: float = 0.05) -> LLMDecider:
    stats = LLMStats()
    slots = [ProviderSlot(p, RateLimiter(rpm=1000, tpm=10_000_000)) for p in providers]
    return LLMDecider(FallbackChain(slots, stats, max_queue_wait_s=1.0), stats, 25, batch_wait_s, 4)


def make_pipeline(decider: LLMDecider) -> DecisionPipeline:
    rules = SafetyRules(PrankTracker(window_s=600, min_reports=3))
    return DecisionPipeline(local=None, llm=decider, rules=rules, conf_threshold=0.8)


def reports(n: int) -> list[Report]:
    return [
        Report(id=f"r{i}", channel="web", caller_hash=None, raw_text=f"incident number {i}", received_at=0.0)
        for i in range(n)
    ]


async def run_with(decider: LLMDecider, n: int, chunks: int = 1) -> list:
    """Decide n reports split across concurrent pipeline batches."""
    pipeline = make_pipeline(decider)
    runner = asyncio.create_task(decider.run())
    try:
        size = n // chunks
        batches = [reports(n)[i * size : (i + 1) * size] for i in range(chunks)]
        results = await asyncio.gather(*(pipeline.decide_batch(b) for b in batches))
        return [r for batch in results for r in batch]
    finally:
        runner.cancel()


async def test_100_uncertain_reports_take_at_most_5_calls() -> None:
    provider = FakeProvider("a", valid_json)
    results = await run_with(make_decider(provider), 100, chunks=4)
    assert len(results) == 100
    assert provider.calls <= 5
    assert all(r.source == "llm" and r.decision.department == "fire" for r in results)
    assert all(r.prompt_version == "decision_v1" for r in results)


async def test_rate_limited_provider_falls_through_to_next() -> None:
    a = FakeProvider("a", ProviderError("a", "HTTP 429", retryable=True, retry_after=5))
    b = FakeProvider("b", valid_json)
    decider = make_decider(a, b)
    results = await run_with(decider, 10)
    assert a.calls == 1 and b.calls == 1
    assert all(r.model == "b/b-model" for r in results)
    # a is now cooling down: the next batch goes straight to b
    await run_with(decider, 5)
    assert a.calls == 1 and b.calls == 2


async def test_all_providers_failing_keeps_local_answer_for_review() -> None:
    a = FakeProvider("a", ProviderError("a", "HTTP 503", retryable=True))
    b = FakeProvider("b", ProviderError("b", "HTTP 500", retryable=True))
    decider = make_decider(a, b)
    results = await run_with(decider, 3)
    assert all(r.source == "local" and r.decision.needs_human_review for r in results)
    assert decider.stats.fallbacks == 3


async def test_malformed_json_retries_once_then_falls_back() -> None:
    provider = FakeProvider("a", lambda user: "Sure! Here are the results: {oops")
    results = await run_with(make_decider(provider), 4)
    assert provider.calls == 2  # one retry, then give up
    assert all(r.source == "local" and r.decision.needs_human_review for r in results)


async def test_partially_invalid_reply_reasks_only_missing_items() -> None:
    seen: list[int] = []

    def respond(user: str) -> str:
        count = len(_LINE.findall(user))
        seen.append(count)
        payload = json.loads(valid_json(user))
        if len(seen) == 1:
            payload["results"][1]["severity"] = 9  # invalid on first try
        return json.dumps(payload)

    results = await run_with(make_decider(FakeProvider("a", respond)), 3)
    assert seen == [3, 1]
    assert all(r.source == "llm" for r in results)


async def test_pipeline_does_not_block_event_loop() -> None:
    slow = FakeProvider("a", valid_json)
    original = slow.complete

    async def delayed(system: str, user: str) -> ProviderReply:
        await asyncio.sleep(0.2)
        return await original(system, user)

    slow.complete = delayed  # type: ignore[method-assign]
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    tick_task = asyncio.create_task(ticker())
    await run_with(make_decider(slow), 25)
    tick_task.cancel()
    assert ticks >= 15  # the loop kept running while the LLM call was in flight


def test_rate_limiter_reports_wait_and_refuses_long_waits() -> None:
    now = [0.0]
    limiter = RateLimiter(rpm=60, tpm=6000, clock=lambda: now[0])
    assert limiter.reserve(100, max_wait_s=1) == 0.0
    for _ in range(59):
        limiter.reserve(1, max_wait_s=1)
    assert limiter.reserve(1, max_wait_s=0.5) is None  # would need ~1 s
    assert limiter.reserve(1, max_wait_s=2) == pytest.approx(1.0, abs=0.05)
