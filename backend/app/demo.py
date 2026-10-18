"""Demo safety net: record the LLM layer during a live run, replay it offline later.

DEMO_RECORD=true appends one JSON line per fast-LLM decision (keyed by the
report's text) and per System 2 reasoning result (keyed by the incident title),
with the latency and tokens the provider reported. DEMO_CACHE=true serves those
answers from the file, after the same delay, instead of calling any provider.

Everything else (local model, rules, clustering, geocoding gazetteer, alerts,
cost ticker) runs for real, so a replayed disaster run behaves like the live one
and stays fully clickable, with no network. Simulated runs are deterministic
(seeded), so the same reports come back and hit the cache.
"""

import asyncio
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from app.decision.llm import DECISION_PROMPT_VERSION, FallbackChain, LLMOutcome, LLMStats
from app.decision.providers import ProviderReply
from app.models import Decision
from app.reasoning.prompting import ReasoningOutput

log = logging.getLogger(__name__)

MAX_REPLAY_DELAY_S = 8.0  # never make the demo wait longer than this on one answer


def text_key(text: str) -> str:
    return " ".join(text.split())


class DemoRecorder:
    """Append-only JSONL writer. Called from the event loop only, so no locking."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file: TextIO = path.open("a", encoding="utf-8")
        self.path = path

    def _write(self, record: dict[str, Any]) -> None:
        self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._file.flush()

    def decision(self, text: str, outcome: LLMOutcome, reply: ProviderReply, share: int) -> None:
        """One answered report; the batch's tokens are split evenly over its ``share`` items."""
        self._write(
            {
                "kind": "decision",
                "text": text_key(text),
                "decision": outcome.decision.model_dump(),
                "provider": outcome.provider,
                "model": outcome.model,
                "latency_s": round(reply.latency_s, 3),
                "input_tokens": reply.input_tokens // share,
                "output_tokens": reply.output_tokens // share,
            }
        )

    def reasoning(self, title: str, output: ReasoningOutput, reply: ProviderReply) -> None:
        self._write(
            {
                "kind": "reasoning",
                "title": title,
                "output": output.model_dump(exclude={"merge_suggestions"}),  # incident ids differ next run
                "provider": reply.provider,
                "model": reply.model,
                "latency_s": round(reply.latency_s, 3),
                "input_tokens": reply.input_tokens,
                "output_tokens": reply.output_tokens,
            }
        )

    def close(self) -> None:
        self._file.close()


@dataclass(frozen=True)
class RecordedDecision:
    decision: Decision
    provider: str
    model: str
    latency_s: float
    input_tokens: int
    output_tokens: int
    call_id: int  # records answered by the same provider reply share one id


@dataclass(frozen=True)
class RecordedReasoning:
    output: ReasoningOutput
    provider: str
    model: str
    latency_s: float
    input_tokens: int
    output_tokens: int

    def charge(self, stats: LLMStats) -> None:
        """Count the recorded call so the cost ticker shows what the live run spent."""
        key = f"{self.provider}/{self.model}"
        stats.calls[key] += 1
        stats.input_tokens[key] += self.input_tokens
        stats.output_tokens[key] += self.output_tokens


@dataclass
class DemoCache:
    decisions: dict[str, RecordedDecision] = field(default_factory=dict)
    reasoning: dict[str, RecordedReasoning] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "DemoCache":
        """Read a recording; the last record for a key wins. O(lines).

        One provider reply is written as consecutive records with the same provider,
        model and latency, which is how the original calls are counted back.
        """
        cache = cls()
        call_id, previous_reply = 0, None
        if not path.exists():
            log.error("demo recording %s not found; replay will fall back to local decisions", path)
            return cache
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if record["kind"] == "decision":
                    reply = (record["provider"], record["model"], record["latency_s"])
                    if reply != previous_reply:
                        call_id, previous_reply = call_id + 1, reply
                    cache.decisions[record["text"]] = RecordedDecision(
                        Decision.model_validate(record["decision"]),
                        record["provider"],
                        record["model"],
                        float(record["latency_s"]),
                        int(record["input_tokens"]),
                        int(record["output_tokens"]),
                        call_id,
                    )
                elif record["kind"] == "reasoning":
                    cache.reasoning[record["title"]] = RecordedReasoning(
                        ReasoningOutput.model_validate(record["output"]),
                        record["provider"],
                        record["model"],
                        float(record["latency_s"]),
                        int(record["input_tokens"]),
                        int(record["output_tokens"]),
                    )
            except (KeyError, ValueError, TypeError) as exc:
                log.warning("skipping bad demo record on line %d: %r", line_no, exc)
        log.info("demo cache: %d decisions, %d reasoning results", len(cache.decisions), len(cache.reasoning))
        return cache


class ReplayDecider:
    """Drop-in for LLMDecider that answers from a recording, after the recorded delay.

    Unknown texts get no answer, exactly like an unavailable provider: the local
    decision stands and is flagged for human review. Tokens and calls are charged
    once per recorded answer and per recorded call, so the cost ticker shows what
    the live run actually spent, however the replayed batches happen to form.
    """

    def __init__(self, cache: DemoCache) -> None:
        self._cache = cache
        self.stats = LLMStats()
        self.chain = FallbackChain([], self.stats, 0.0)  # no providers: nothing touches the network
        self.prompt_version = DECISION_PROMPT_VERSION
        self.hits = 0
        self.misses = 0
        self._charged: set[str] = set()
        self._calls_seen: set[int] = set()

    async def decide(self, texts: Sequence[str]) -> list[LLMOutcome | None]:
        found = [self._cache.decisions.get(text_key(t)) for t in texts]
        delays = [r.latency_s for r in found if r is not None]
        if delays:
            await asyncio.sleep(min(MAX_REPLAY_DELAY_S, max(delays)))
        outcomes: list[LLMOutcome | None] = []
        for text, record in zip(texts, found, strict=True):
            if record is None:
                self.misses += 1
                self.stats.fallbacks += 1
                outcomes.append(None)
                continue
            self.hits += 1
            self._charge(text_key(text), record)
            outcomes.append(LLMOutcome(record.decision, record.provider, record.model))
        self.stats.batches += 1
        self.stats.items += len(texts)
        return outcomes

    def _charge(self, key: str, record: RecordedDecision) -> None:
        if key in self._charged:
            return
        self._charged.add(key)
        model = f"{record.provider}/{record.model}"
        self.stats.input_tokens[model] += record.input_tokens
        self.stats.output_tokens[model] += record.output_tokens
        if record.call_id not in self._calls_seen:
            self._calls_seen.add(record.call_id)
            self.stats.calls[model] += 1

    async def run(self) -> None:
        """Nothing to batch: present so the app can treat both deciders alike."""
        await asyncio.Event().wait()
