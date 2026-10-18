"""System 2 scheduler: reasons about complex incidents in the background, debounced.

``consider`` is called after every commit or revision and is O(k) per incident
(one nearby lookup). An incident qualifies when it has at least
``min_reports`` reports, two or more distinct hazards, or another open incident
within ``neighbor_m`` updated in the last ``neighbor_window_s``. It then runs at
most once per ``debounce_s``, and only when its reports or hazards changed since
the last run. One loop over a min-heap of due times does the work, bounded by a
semaphore, so dispatch never waits for the reasoning model.
"""

import asyncio
import heapq
import itertools
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from app.cluster.index import haversine_km
from app.cluster.service import IncidentService
from app.db import Database
from app.decision.llm import AllProvidersFailed, FallbackChain, load_prompt
from app.models import Incident
from app.reasoning.prompting import REASONING_PROMPT_VERSION, build_message, parse_reasoning
from app.ws import Broadcaster

log = logging.getLogger(__name__)

CHARS_PER_TOKEN = 2.5
MAX_OUTPUT_TOKENS = 700
SAMPLES_PER_NEIGHBOUR = 2
MAX_NEIGHBOURS = 4
MAX_BACKOFF_S = 300.0

Signature = tuple[int, tuple[str, ...]]


@dataclass(frozen=True)
class ReasonerConfig:
    debounce_s: float = 20.0
    min_reports: int = 3
    min_severity: int = 3
    neighbor_m: float = 300.0
    neighbor_window_s: float = 900.0
    max_reports: int = 30
    concurrency: int = 2


@dataclass
class ReasonerStats:
    runs: int = 0
    applied: int = 0
    deferred: int = 0  # no provider available (quota/rate limits): retried with backoff
    failed: int = 0  # provider answered but the output was unusable twice
    skipped_unchanged: int = 0
    by_model: dict[str, int] = field(default_factory=dict)


class Reasoner:
    def __init__(
        self,
        incidents: IncidentService,
        db: Database,
        chain: FallbackChain,
        broadcaster: Broadcaster,
        config: ReasonerConfig,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._incidents = incidents
        self._db = db
        self.chain = chain
        self._broadcaster = broadcaster
        self._config = config
        self._clock = clock
        self._wall = wall_clock
        self._system = load_prompt(REASONING_PROMPT_VERSION)
        self._heap: list[tuple[float, int, str]] = []
        self._seq = itertools.count()
        self._pending: set[str] = set()
        self._last_run: dict[str, float] = {}
        self._last_signature: dict[str, Signature] = {}
        self._deferrals: dict[str, int] = {}
        self._priority: dict[str, tuple[int, int]] = {}
        self._wake = asyncio.Event()
        self._slots = asyncio.Semaphore(config.concurrency)
        self._tasks: set[asyncio.Task[None]] = set()
        self.stats = ReasonerStats()

    @staticmethod
    def signature(incident: Incident) -> Signature:
        """What new reports can change. Excludes the reasoner's own output, which would
        otherwise re-trigger it forever."""
        return incident.report_count, tuple(sorted(incident.linked_hazards))

    def _nearby(self, incident: Incident) -> list[Incident]:
        return self._incidents.nearby(
            incident.id, self._config.neighbor_m / 1000, self._config.neighbor_window_s
        )

    def qualifies(self, incident: Incident) -> bool:
        """Complex enough for System 2? O(k) for the nearby lookup."""
        if incident.status == "merged" or incident.silent_sos or incident.severity < self._config.min_severity:
            return False
        return (
            incident.report_count >= self._config.min_reports
            or len(incident.linked_hazards) >= 2
            or bool(self._nearby(incident))
        )

    def consider(self, incidents: Sequence[Incident]) -> None:
        """Schedule qualifying incidents; never blocks. O(k) per incident."""
        now = self._clock()
        for incident in incidents:
            if incident.id in self._pending or not self.qualifies(incident):
                continue
            if self._last_signature.get(incident.id) == self.signature(incident):
                self.stats.skipped_unchanged += 1
                continue
            due = max(now, self._last_run.get(incident.id, float("-inf")) + self._config.debounce_s)
            self._priority[incident.id] = (incident.severity, incident.report_count)
            heapq.heappush(self._heap, (due, next(self._seq), incident.id))
            self._pending.add(incident.id)
            self._wake.set()

    def due(self) -> list[str]:
        """Pop every incident whose debounce has elapsed, most severe and largest first.

        O(log p) per pop plus O(r log r) to order the r ready incidents.
        """
        now = self._clock()
        ready: list[str] = []
        while self._heap and self._heap[0][0] <= now:
            _, _, incident_id = heapq.heappop(self._heap)
            self._pending.discard(incident_id)
            ready.append(incident_id)
        return sorted(ready, key=lambda i: self._priority.get(i, (0, 0)), reverse=True)

    def _retry_later(self, incident_id: str) -> None:
        """Exponential backoff per incident while no provider can take the call."""
        attempt = self._deferrals.get(incident_id, 0)
        self._deferrals[incident_id] = attempt + 1
        delay = min(MAX_BACKOFF_S, self._config.debounce_s * 2**attempt)
        heapq.heappush(self._heap, (self._clock() + delay, next(self._seq), incident_id))
        self._pending.add(incident_id)
        self._wake.set()

    async def run(self) -> None:
        try:
            while True:
                timeout = max(0.0, self._heap[0][0] - self._clock()) if self._heap else None
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout)
                except TimeoutError:
                    pass
                for incident_id in self.due():
                    await self._slots.acquire()
                    task = asyncio.create_task(self._guarded(incident_id))
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)
        finally:
            for task in self._tasks:
                task.cancel()

    async def _guarded(self, incident_id: str) -> None:
        try:
            await self.reason(incident_id)
        except Exception:
            self.stats.failed += 1
            log.exception("reasoning failed for incident %s", incident_id)
        finally:
            self._slots.release()

    async def reason(self, incident_id: str) -> Incident | None:
        """One System 2 pass: build input, ask, ground, store. Retries the parse once."""
        self._last_run[incident_id] = self._clock()
        incident, reports = await self._incidents.reasoning_input(incident_id, self._config.max_reports)
        if incident.status == "merged":
            return None
        signature = self.signature(incident)
        nearby = await self._neighbour_samples(incident)
        user = build_message(incident, reports, nearby, self._wall())
        est_input = int((len(self._system) + len(user)) / CHARS_PER_TOKEN)
        allowed = {other.id for other, _, _ in nearby}
        self.stats.runs += 1
        for _attempt in range(2):
            try:
                reply = await self.chain.complete(self._system, user, est_input, 300, MAX_OUTPUT_TOKENS)
            except AllProvidersFailed:
                self.stats.deferred += 1
                self._retry_later(incident_id)
                return None
            parsed = parse_reasoning(reply.text, allowed)
            if parsed is None:
                continue
            model = f"{reply.provider}/{reply.model}"
            self.stats.by_model[model] = self.stats.by_model.get(model, 0) + 1
            updated = await self._incidents.apply_reasoning(
                incident_id,
                risk_hazards=parsed.linked_hazards,
                combined_risk=parsed.combined_risk,
                merge_suggestions=parsed.merge_suggestions,
                briefing=parsed.briefing,
                actor=model,
                prompt_version=REASONING_PROMPT_VERSION,
            )
            self._last_signature[incident_id] = signature
            self._deferrals.pop(incident_id, None)
            self.stats.applied += 1
            self._broadcaster.publish("incident.updated", updated.model_dump(mode="json"))
            return updated
        # The model answered twice but neither answer was usable: back off too.
        self.stats.failed += 1
        self._retry_later(incident_id)
        return None

    async def _neighbour_samples(self, incident: Incident) -> list[tuple[Incident, float, list[str]]]:
        """Nearby incidents with distance and a couple of their newest report texts."""
        found: list[tuple[Incident, float, list[str]]] = []
        for other in self._nearby(incident)[:MAX_NEIGHBOURS]:
            if incident.lat is None or incident.lng is None or other.lat is None or other.lng is None:
                continue
            distance = haversine_km(incident.lat, incident.lng, other.lat, other.lng) * 1000
            rows = await self._db.incident_reports(other.id)
            found.append((other, distance, [r.raw_text for r, _ in rows[-SAMPLES_PER_NEIGHBOUR:]]))
        return found
