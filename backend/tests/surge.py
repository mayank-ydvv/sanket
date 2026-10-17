"""Synthetic surge: many reports about a few seeded events (test helper)."""

import random
from dataclasses import dataclass

from app.cluster.location import GAZETTEER
from app.corpus import EVENTS, FRAMES, LANGUAGES, PANIC, add_typos


@dataclass(frozen=True)
class SurgeReport:
    event: int
    text: str
    department: str
    location: str | None


def seeded_events(count: int, rng: random.Random) -> list[tuple[str, int, str]]:
    """(department, event index, place name) at distinct places, each event with its own
    phrasing. Event indices are language-aligned in the corpus, so one event reads the
    same in every language."""
    places = rng.sample([p.name for p in GAZETTEER], count)
    departments = ("fire", "police", "medical", "disaster", "utilities")
    phrasings = {d: rng.sample(range(8), 8) for d in departments}
    return [(departments[i % 5], phrasings[departments[i % 5]][i // 5], places[i]) for i in range(count)]


def surge(events: list[tuple[str, int, str]], n: int, rng: random.Random) -> list[SurgeReport]:
    reports = []
    for k in range(n):
        e = k % len(events)
        department, idx, place = events[e]
        language = rng.choice(LANGUAGES)
        frame = rng.choice(FRAMES[language])
        text = frame.replace("{event}", EVENTS[language][department][idx].text)
        located = "{loc}" in text
        text = text.replace("{loc}", place)
        if rng.random() < 0.3:
            text = f"{rng.choice(PANIC[language])} {text}"
        if rng.random() < 0.3:
            text = add_typos(text, language, rng)
        reports.append(SurgeReport(e, text, department, place if located else None))
    rng.shuffle(reports)
    return reports
