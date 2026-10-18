"""English translations for reports the fast LLM never saw.

Uncertain reports get their translation for free inside the fast-LLM decision
(prompt decision_v3). Reports the local model was sure about are translated
here, on demand, when a dispatcher opens their incident: one batched call on the
System 1 provider chain (same quotas, same cost ticker), at most once per report.
"""

import asyncio
import json
import logging
import re
from collections.abc import Sequence
from typing import Any

from app.decision.llm import CHARS_PER_TOKEN, AllProvidersFailed, FallbackChain, format_reports, load_prompt
from app.demo import MAX_REPLAY_DELAY_S, DemoCache, DemoRecorder, text_key

log = logging.getLogger(__name__)

TRANSLATE_PROMPT_VERSION = "translate_v1"
MAX_BATCH = 30
OUTPUT_TOKENS_PER_ITEM = 45
OUTPUT_CAP_BASE = 64
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


def parse_translations(text: str, count: int) -> dict[int, str]:
    """``{"t": [{"i": 0, "en": "..."}]}`` into translations keyed by index. O(n)."""
    try:
        payload: Any = json.loads(_FENCE.sub("", text.strip()))
    except json.JSONDecodeError:
        return {}
    items = payload.get("t") if isinstance(payload, dict) else payload
    found: dict[int, str] = {}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        idx, english = item.get("i"), item.get("en")
        if isinstance(idx, int) and isinstance(english, str) and 0 <= idx < count and idx not in found:
            found[idx] = " ".join(english.split())[:500]
    return found


class Translator:
    def __init__(
        self,
        chain: FallbackChain,
        recorder: DemoRecorder | None = None,
        replay: DemoCache | None = None,
    ) -> None:
        self.chain = chain
        self._system = load_prompt(TRANSLATE_PROMPT_VERSION)
        self._recorder = recorder
        self._replay = replay
        self._replay_charged: set[str] = set()

    @property
    def available(self) -> bool:
        return self._replay is not None or bool(self.chain.slots)

    async def translate(self, texts: Sequence[str]) -> list[str | None]:
        """English for each text ("" if already English); None where no answer came back."""
        texts = list(texts)[:MAX_BATCH]
        if not texts:
            return []
        if self._replay is not None:
            return await self._from_recording(self._replay, texts)
        user = format_reports(texts).replace('{"r": [...]}', '{"t": [...]}')
        est_input = int((len(self._system) + len(user)) / CHARS_PER_TOKEN)
        cap = OUTPUT_CAP_BASE + OUTPUT_TOKENS_PER_ITEM * 2 * len(texts)
        try:
            reply = await self.chain.complete(self._system, user, est_input, OUTPUT_TOKENS_PER_ITEM * len(texts), cap)
        except AllProvidersFailed:
            log.warning("no provider available to translate %d reports", len(texts))
            return [None] * len(texts)
        found = parse_translations(reply.text, len(texts))
        if self._recorder is not None:
            for idx, english in found.items():
                self._recorder.translation(texts[idx], english, reply, len(found))
        return [found.get(i) for i in range(len(texts))]

    async def _from_recording(self, replay: DemoCache, texts: list[str]) -> list[str | None]:
        """Demo replay: recorded translations after the recorded delay, charged once each."""
        keys = [text_key(t) for t in texts]
        found = [replay.translations.get(k) for k in keys]
        delays = [r.latency_s for r in found if r is not None]
        if delays:
            await asyncio.sleep(min(MAX_REPLAY_DELAY_S, max(delays)))
        models: set[str] = set()
        for key, record in zip(keys, found, strict=True):
            if record is None or key in self._replay_charged:
                continue
            self._replay_charged.add(key)
            model = f"{record.provider}/{record.model}"
            models.add(model)
            self.chain.stats.input_tokens[model] += record.input_tokens
            self.chain.stats.output_tokens[model] += record.output_tokens
        for model in models:
            self.chain.stats.calls[model] += 1
        return [r.english if r is not None else None for r in found]
