"""Disaster mode: a seeded surge of reports about a dozen events, streamed into the real pipeline.

The generator reuses the corpus's language-aligned event phrasings, so one event
reads the same in every language, and adds what a real surge has: people calling
back about the same event, panic and typos, a prank caller with contradicting
reports, silent SOS calls, non-urgent noise, and two different clues (smoke,
gas smell) about one building.
"""

import asyncio
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from app.corpus import (
    ESCALATORS,
    ESCALATORS_BY_DEPARTMENT,
    EVENTS,
    FRAMES,
    LATIN_LANGUAGES,
    NON_URGENT,
    PANIC,
    PRANKS,
    add_typos,
)
from app.intake.service import Intake
from app.models import Channel
from app.ws import Broadcaster

log = logging.getLogger(__name__)

Scenario = Literal["flood"]
Kind = Literal["event", "prank", "silent_sos", "non_urgent"]

LANGUAGE_WEIGHTS: dict[str, float] = {"hinglish": 0.3, "hi": 0.25, "en": 0.2, "ta": 0.12, "bn": 0.13}
CHANNEL_WEIGHTS: dict[Channel, float] = {"sms": 0.35, "whatsapp": 0.3, "call": 0.25, "web": 0.1}
SHARE_NON_URGENT = 0.03
SHARE_GENERIC_PRANK = 0.02
PRANK_CALLER_REPORTS = 6
SILENT_SOS_TEXTS = ("1111 1111 1111", "... --- ...")
P_PANIC, P_TYPO, P_ESCALATOR = 0.35, 0.3, 0.25
PROGRESS_EVERY = 25


@dataclass(frozen=True)
class SeedEvent:
    """One real-world event: department, aligned phrasing indices, place, share of traffic."""

    department: str
    phrasings: tuple[int, ...]
    place: str
    weight: float


FLOOD_EVENTS: tuple[SeedEvent, ...] = (
    SeedEvent("disaster", (0,), "Sector 137", 3.0),  # people on rooftops
    SeedEvent("disaster", (0,), "Kalindi Kunj bridge", 2.0),
    SeedEvent("disaster", (5,), "Sector 93 expressway", 2.0),  # bus stuck in underpass
    SeedEvent("disaster", (1,), "Mamura chowk", 1.5),  # wall collapse
    SeedEvent("disaster", (7,), "Film City", 1.5),  # river overflowing
    SeedEvent("utilities", (0,), "Sector 76", 1.5),  # live wire in water
    SeedEvent("utilities", (1,), "Sector 104 crossing", 1.0),  # transformer burst
    SeedEvent("medical", (1,), "Botanical Garden metro", 1.0),
    SeedEvent("medical", (2,), "Pari Chowk", 1.0),
    SeedEvent("fire", (5, 1), "Gaur City 2", 1.5),  # gas smell + fire upstairs: one building, two clues
    SeedEvent("police", (4,), "Atta market", 0.8),  # looting
    SeedEvent("fire", (0,), "Sector 12 market", 0.8),
)
SCENARIOS: dict[str, tuple[SeedEvent, ...]] = {"flood": FLOOD_EVENTS}


@dataclass(frozen=True)
class SimReport:
    text: str
    channel: Channel
    caller: str
    kind: Kind
    event: int | None = None


def _pick(rng: random.Random, weights: dict[Any, float]) -> Any:
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def _event_text(event: SeedEvent, language: str, rng: random.Random) -> str:
    department = event.department
    phrase = EVENTS[language][department][rng.choice(event.phrasings)].text
    keys = ESCALATORS_BY_DEPARTMENT.get(department, ())
    if keys and rng.random() < P_ESCALATOR:
        phrase = f"{phrase}, {ESCALATORS[language][rng.choice(keys)]}"
    text = rng.choice(FRAMES[language]).replace("{event}", phrase).replace("{loc}", event.place)
    if rng.random() < P_PANIC:
        panic = rng.choice(PANIC[language])
        text = f"{panic} {text}" if rng.random() < 0.5 else f"{text} {panic}"
    if language in LATIN_LANGUAGES and rng.random() < 0.08:
        text = text.upper()
    return add_typos(text, language, rng) if rng.random() < P_TYPO else text


def generate(scenario: Scenario, n: int, seed: int = 7) -> list[SimReport]:
    """Deterministic surge of ``n`` reports. O(n)."""
    rng = random.Random(seed)
    events = SCENARIOS[scenario]
    reports: list[SimReport] = [
        SimReport(text, "call" if i == 0 else "sms", f"+9199900000{i:02d}", "silent_sos")
        for i, text in enumerate(SILENT_SOS_TEXTS[: max(0, min(2, n // 100))])
    ]
    prank_caller = "+919888800000"
    for _ in range(PRANK_CALLER_REPORTS if n >= 100 else 0):
        decoy = rng.choice(events)
        others = [d for d in ("fire", "police", "medical", "disaster") if d != decoy.department]
        department = rng.choice(others)
        language = _pick(rng, LANGUAGE_WEIGHTS)
        phrase = rng.choice(EVENTS[language][department][:6]).text
        reports.append(SimReport(f"{phrase} {decoy.place}", "sms", prank_caller, "prank"))
    callers: dict[int, list[str]] = {i: [] for i in range(len(events))}
    weights = [e.weight for e in events]
    while len(reports) < n:
        roll = rng.random()
        language = _pick(rng, LANGUAGE_WEIGHTS)
        channel: Channel = _pick(rng, CHANNEL_WEIGHTS)
        if roll < SHARE_NON_URGENT:
            template = rng.choice(NON_URGENT[language])
            text = template.text.replace("{loc}", rng.choice(events).place)
            reports.append(SimReport(text, channel, f"+9197{rng.randrange(10**8):08d}", "non_urgent"))
            continue
        if roll < SHARE_NON_URGENT + SHARE_GENERIC_PRANK:
            text = rng.choice(PRANKS[language]).replace("{loc}", rng.choice(events).place)
            reports.append(SimReport(text, channel, f"+9196{rng.randrange(10**8):08d}", "prank"))
            continue
        index = rng.choices(range(len(events)), weights=weights)[0]
        pool = callers[index]
        if pool and rng.random() < 0.25:  # someone calling back about the same event
            caller = rng.choice(pool)
        else:
            caller = f"+9198{index:02d}{rng.randrange(10**6):06d}"
            pool.append(caller)
        reports.append(SimReport(_event_text(events[index], language, rng), channel, caller, "event", index))
    rng.shuffle(reports)
    return reports


@dataclass
class SimulationStatus:
    id: str = "simulation"
    scenario: str | None = None
    running: bool = False
    total: int = 0
    submitted: int = 0
    decided: int = 0
    events: int = 0
    started_at: float | None = None
    submitted_s: float | None = None
    decided_s: float | None = None
    error: str | None = None
    _baseline: int = field(default=0, repr=False)

    def public(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


class SimulationRunner:
    """Streams one generated surge at a steady rate; only one run at a time."""

    def __init__(
        self,
        intake: Intake,
        broadcaster: Broadcaster,
        decided_count: Callable[[], int],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._intake = intake
        self._broadcaster = broadcaster
        self._decided = decided_count
        self._clock = clock
        self.status = SimulationStatus()
        self._task: asyncio.Task[None] | None = None

    def start(self, scenario: Scenario, n: int, seconds: float, seed: int) -> SimulationStatus:
        if self.status.running:
            raise RuntimeError("a simulation is already running")
        reports = generate(scenario, n, seed)
        self.status = SimulationStatus(
            scenario=scenario,
            running=True,
            total=len(reports),
            events=len(SCENARIOS[scenario]),
            started_at=time.time(),
            _baseline=self._decided(),
        )
        self._task = asyncio.create_task(self._run(reports, seconds))
        return self.status

    def cancel(self) -> None:
        if self._task is not None:
            self._task.cancel()

    def _publish(self) -> None:
        self.status.decided = self._decided() - self.status._baseline
        self._broadcaster.publish("simulation.updated", self.status.public())

    async def _run(self, reports: list[SimReport], seconds: float) -> None:
        """Submit at n/seconds per second, then wait (bounded) for the pipeline to catch up."""
        start = self._clock()
        interval = seconds / max(1, len(reports))
        try:
            for i, report in enumerate(reports):
                delay = start + i * interval - self._clock()
                if delay > 0:
                    await asyncio.sleep(delay)
                await self._intake.submit(report.text, report.channel, report.caller)
                self.status.submitted = i + 1
                if (i + 1) % PROGRESS_EVERY == 0:
                    self._publish()
            self.status.submitted_s = self._clock() - start
            deadline = self._clock() + max(60.0, seconds * 3)
            while self._decided() - self.status._baseline < len(reports) and self._clock() < deadline:
                self._publish()
                await asyncio.sleep(0.25)
            if self._decided() - self.status._baseline >= len(reports):
                self.status.decided_s = self._clock() - start
        except Exception as exc:
            log.exception("simulation failed")
            self.status.error = repr(exc)
        finally:
            self.status.running = False
            self._publish()
