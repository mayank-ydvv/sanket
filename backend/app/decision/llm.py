"""Fast-LLM fallback for uncertain reports: micro-batching, provider chain, strict parsing.

Uncertain reports from any number of concurrent pipeline batches are pooled for up
to ``batch_wait_s`` or ``batch_size`` items and sent as ONE request asking for a
JSON array, so n uncertain reports cost about n / batch_size calls.
"""

import asyncio
import json
import logging
import random
import re
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.decision.providers import Provider, ProviderError, ProviderReply, RateLimiter
from app.models import Decision, Department

if TYPE_CHECKING:
    from app.demo import DemoRecorder

log = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
DECISION_PROMPT_VERSION = "decision_v2"
COOLDOWN_BASE_S = 2.0
COOLDOWN_MAX_S = 60.0
CHARS_PER_TOKEN = 2.5
OUTPUT_TOKENS_PER_ITEM = 40
# Hard cap on reply length: generous headroom over the estimate, so a valid reply
# is never truncated while a runaway one cannot eat the output quota.
OUTPUT_CAP_PER_ITEM = 60
OUTPUT_CAP_BASE = 128
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def load_prompt(version: str) -> str:
    return (PROMPTS_DIR / f"{version}.txt").read_text(encoding="utf-8")


class LLMItem(BaseModel):
    """One element of the model's compact JSON array (prompt decision_v2).

    Short keys keep output tokens low, which is what bounds both latency and the
    free tiers' output-token quotas. Strict types; unknown keys are ignored.
    """

    model_config = ConfigDict(strict=True, extra="ignore")

    idx: int = Field(alias="i")
    is_emergency: bool = Field(alias="e")
    emergency_prob: float = Field(alias="p", ge=0.0, le=1.0)
    department: Department = Field(alias="d")
    department_conf: float = Field(alias="dc", ge=0.0, le=1.0)
    severity: int = Field(alias="s", ge=1, le=5)
    alert_now: bool = Field(False, alias="a")
    location_text: str | None = Field(None, alias="loc")
    people_at_risk: str | None = Field(None, alias="risk")
    hazards: list[str] = Field(default_factory=list, alias="hz")
    silent_sos: bool = Field(False, alias="sos")
    prank_score: float = Field(0.0, alias="pr", ge=0.0, le=1.0)
    needs_human_review: bool = Field(False, alias="rev")

    def to_decision(self) -> Decision:
        return Decision(**self.model_dump(exclude={"idx"}))


def _salvage_objects(text: str) -> list[Any]:
    """Every complete JSON object inside the first array of a truncated reply. O(L)."""
    start = text.find("[")
    if start < 0:
        return []
    decoder = json.JSONDecoder()
    items: list[Any] = []
    pos = start + 1
    while True:
        while pos < len(text) and text[pos] in " \t\r\n,":
            pos += 1
        if pos >= len(text) or text[pos] != "{":
            return items
        try:
            obj, pos = decoder.raw_decode(text, pos)
        except json.JSONDecodeError:
            return items
        items.append(obj)


def parse_decisions(text: str, count: int) -> dict[int, Decision]:
    """Parse ``{"r": [...]}`` (or a bare array) into decisions keyed by idx. O(n).

    Items that fail validation, repeat an idx or fall outside ``[0, count)`` are dropped,
    so one bad item never discards the rest of the batch. A reply cut off by the
    output cap still yields its complete items; the caller re-asks for the rest.
    """
    cleaned = _FENCE.sub("", text.strip())
    try:
        payload: Any = json.loads(cleaned)
        items = payload.get("r") if isinstance(payload, dict) else payload
    except json.JSONDecodeError:
        items = _salvage_objects(cleaned)
    if not isinstance(items, list):
        return {}
    decisions: dict[int, Decision] = {}
    for raw in items:
        try:
            item = LLMItem.model_validate(raw)
        except ValidationError:
            continue
        if 0 <= item.idx < count and item.idx not in decisions:
            decisions[item.idx] = item.to_decision()
    return decisions


def format_reports(texts: Sequence[str]) -> str:
    """Numbered, single-line report list for the user message. O(total L)."""
    lines = (f"[{i}] {' '.join(text.split()) or '(empty report)'}" for i, text in enumerate(texts))
    return (
        "Reports:\n" + "\n".join(lines) + f"\n\nReturn {{\"r\": [...]}} with exactly {len(texts)} objects."
    )


class AllProvidersFailed(Exception):
    pass


@dataclass
class ProviderSlot:
    provider: Provider
    limiter: RateLimiter
    failures: int = 0
    cooldown_until: float = 0.0


@dataclass
class LLMStats:
    calls: Counter[str] = field(default_factory=Counter)
    failures: Counter[str] = field(default_factory=Counter)
    input_tokens: Counter[str] = field(default_factory=Counter)
    output_tokens: Counter[str] = field(default_factory=Counter)
    batches: int = 0
    items: int = 0
    fallbacks: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": sum(self.calls.values()),
            "calls_by_provider": dict(self.calls),
            "failures_by_provider": dict(self.failures),
            "input_tokens": dict(self.input_tokens),
            "output_tokens": dict(self.output_tokens),
            "batches": self.batches,
            "items": self.items,
            "fallbacks_to_local": self.fallbacks,
        }


class FallbackChain:
    """Tries providers in order. A 429/5xx puts that provider in an exponential,
    jittered cooldown and the request moves on to the next provider at once, so a
    rate limit slows the system down instead of stalling it."""

    def __init__(
        self,
        slots: Sequence[ProviderSlot],
        stats: LLMStats,
        max_queue_wait_s: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.slots = list(slots)
        self.stats = stats
        self._max_queue_wait_s = max_queue_wait_s
        self._clock = clock
        self._sleep = sleep

    def _cool_down(self, slot: ProviderSlot, error: ProviderError) -> None:
        """Retryable errors back off exponentially with jitter; hard errors (bad key,
        retired model) park the provider for the maximum cooldown."""
        if not error.retryable:
            slot.cooldown_until = self._clock() + COOLDOWN_MAX_S
            return
        slot.failures += 1
        backoff = min(COOLDOWN_MAX_S, COOLDOWN_BASE_S * 2 ** (slot.failures - 1))
        delay = max(backoff * (0.5 + random.random()), error.retry_after or 0.0)
        slot.cooldown_until = self._clock() + delay

    async def complete(
        self, system: str, user: str, est_input: int, est_output: int, max_output_tokens: int
    ) -> ProviderReply:
        """One successful reply from the first usable provider. O(p) attempts for p providers."""
        for slot in self.slots:
            name = f"{slot.provider.name}/{slot.provider.model}"
            if self._clock() < slot.cooldown_until:
                continue
            wait = slot.limiter.reserve(est_input, est_output, self._max_queue_wait_s)
            if wait is None:
                continue
            if wait > 0:
                await self._sleep(wait)
            self.stats.calls[name] += 1
            cap = min(max_output_tokens, slot.limiter.max_output_tokens or max_output_tokens)
            try:
                reply = await slot.provider.complete(system, user, cap)
            except ProviderError as error:
                self.stats.failures[name] += 1
                log.warning("LLM provider failed: %s", error)
                self._cool_down(slot, error)
                continue
            slot.failures = 0
            self.stats.input_tokens[name] += reply.input_tokens
            self.stats.output_tokens[name] += reply.output_tokens
            return reply
        raise AllProvidersFailed("no LLM provider available")


@dataclass(frozen=True)
class LLMOutcome:
    decision: Decision
    provider: str
    model: str


class Decider(Protocol):
    """What the pipeline needs from System 1's LLM stage (live batcher or demo replay)."""

    prompt_version: str

    async def decide(self, texts: Sequence[str]) -> list[LLMOutcome | None]: ...


@dataclass
class _Pending:
    text: str
    future: asyncio.Future[LLMOutcome | None]


class LLMDecider:
    """Micro-batching front end to the provider chain. Start ``run()`` as a background task."""

    def __init__(
        self,
        chain: FallbackChain,
        stats: LLMStats,
        batch_size: int,
        batch_wait_s: float,
        max_concurrency: int,
        prompt_version: str = DECISION_PROMPT_VERSION,
        output_cap_per_item: int = OUTPUT_CAP_PER_ITEM,
        recorder: "DemoRecorder | None" = None,
    ) -> None:
        self.chain = chain
        self._recorder = recorder
        self.stats = stats
        self.prompt_version = prompt_version
        self._system = load_prompt(prompt_version)
        self._batch_size = batch_size
        self._batch_wait_s = batch_wait_s
        self._output_cap_per_item = output_cap_per_item
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._queue: asyncio.Queue[_Pending] = asyncio.Queue()
        self._tasks: set[asyncio.Task[None]] = set()

    async def decide(self, texts: Sequence[str]) -> list[LLMOutcome | None]:
        """Queue texts and await their results (None = LLM unavailable or invalid output)."""
        loop = asyncio.get_running_loop()
        pending = [_Pending(text, loop.create_future()) for text in texts]
        for item in pending:
            self._queue.put_nowait(item)
        return list(await asyncio.gather(*(p.future for p in pending)))

    async def run(self) -> None:
        """Collect batches forever and dispatch each one concurrently (bounded)."""
        try:
            while True:
                batch = await self._collect()
                await self._semaphore.acquire()
                task = asyncio.create_task(self._dispatch(batch))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
        finally:
            for task in self._tasks:
                task.cancel()

    async def _collect(self) -> list[_Pending]:
        """Block for the first item, then gather until full or the wait elapses. O(b)."""
        batch = [await self._queue.get()]
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._batch_wait_s
        while len(batch) < self._batch_size:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                batch.append(await asyncio.wait_for(self._queue.get(), remaining))
            except TimeoutError:
                break
        return batch

    def _estimate_tokens(self, user: str, items: int) -> tuple[int, int]:
        """(input, output) token estimates used to reserve rate-limit budget. O(1)."""
        return int((len(self._system) + len(user)) / CHARS_PER_TOKEN), OUTPUT_TOKENS_PER_ITEM * items

    async def _dispatch(self, batch: list[_Pending]) -> None:
        """Ask once; re-ask once for any items that came back missing or invalid."""
        try:
            self.stats.batches += 1
            self.stats.items += len(batch)
            outcomes: list[LLMOutcome | None] = [None] * len(batch)
            todo = list(range(len(batch)))
            for _attempt in range(2):
                user = format_reports([batch[i].text for i in todo])
                try:
                    reply = await self.chain.complete(
                        self._system,
                        user,
                        *self._estimate_tokens(user, len(todo)),
                        max_output_tokens=OUTPUT_CAP_BASE + self._output_cap_per_item * len(todo),
                    )
                except AllProvidersFailed:
                    break
                decisions = parse_decisions(reply.text, len(todo))
                for local_idx, decision in decisions.items():
                    outcome = LLMOutcome(decision, reply.provider, reply.model)
                    outcomes[todo[local_idx]] = outcome
                    if self._recorder is not None:
                        self._recorder.decision(batch[todo[local_idx]].text, outcome, reply, len(todo))
                todo = [todo[i] for i in range(len(todo)) if i not in decisions]
                if not todo:
                    break
            self.stats.fallbacks += sum(o is None for o in outcomes)
            for item, outcome in zip(batch, outcomes, strict=True):
                if not item.future.done():
                    item.future.set_result(outcome)
        except Exception:
            log.exception("LLM batch dispatch failed; falling back to local decisions")
            for item in batch:
                if not item.future.done():
                    self.stats.fallbacks += 1
                    item.future.set_result(None)
        finally:
            self._semaphore.release()
