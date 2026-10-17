"""Generate ``data/train.jsonl`` and ``data/test.jsonl`` from the template corpus.

Run from ``backend/``: ``python -m scripts.gen_data``. Deterministic for a given seed.

Leakage control: every third emergency event, non-urgent template and prank of
each language is held out for the test split, so test phrasings are never seen
in training (sentence frames and place names are shared). Training additionally
draws on a generic per-department lexicon that never appears in the test split. Texts are
de-duplicated across both splits. 50 test rows are marked ``hidden`` and are only
used by the final benchmark.
"""

import argparse
import random
from collections.abc import Sequence
from pathlib import Path
from typing import TypeVar

from app.corpus import (
    DEPARTMENTS,
    ESCALATORS,
    ESCALATORS_BY_DEPARTMENT,
    EVENTS,
    FRAMES,
    HARD_CASES,
    LANGUAGES,
    LEXICON,
    LEXICON_SEVERITY,
    LOCATIONS,
    NON_URGENT,
    PANIC,
    PRANKS,
    VAGUE_LOCATIONS,
    Event,
    LATIN_LANGUAGES,
    HardCase,
    Template,
    add_typos,
)
from scripts.dataset import TEST_PATH, TRAIN_PATH, Category, LabeledReport

QUOTAS: dict[str, dict[Category, int]] = {
    "train": {"emergency": 360, "non_urgent": 150, "prank": 90},
    "test": {"emergency": 150, "non_urgent": 62, "prank": 38},
}
HIDDEN_TEST_ROWS = 50
P_VAGUE_LOCATION = 0.15
P_ESCALATOR = 0.3
P_PANIC = 0.35
P_TYPO = 0.3
P_SHOUT = 0.1
T = TypeVar("T")


def in_split(index: int, split: str) -> bool:
    """Every third item is test-only. O(1)."""
    return (index % 3 == 2) == (split == "test")


def held_out(items: Sequence[T], split: str) -> list[T]:
    return [item for i, item in enumerate(items) if in_split(i, split)]


def event_pool(language: str, department: str, split: str) -> list[Event]:
    """Held-out events for the split; training also gets the domain lexicon. O(k)."""
    pool = held_out(EVENTS[language][department], split)
    if split == "train":
        severity = LEXICON_SEVERITY[department]
        pool += [Event(severity, word) for word in LEXICON[language][department]]
    return pool


def pick_template(
    language: str, category: Category, index: int, split: str, rng: random.Random
) -> Template:
    """Draw one template for a category; emergencies are an event placed in a frame. O(1)."""
    if category == "emergency":
        department = DEPARTMENTS[(index // len(LANGUAGES)) % len(DEPARTMENTS)]
        event = rng.choice(event_pool(language, department, split))
        frame = rng.choice(FRAMES[language])
        return Template(department, event.severity, frame.replace("{event}", event.text))
    if category == "non_urgent":
        return rng.choice(held_out(NON_URGENT[language], split))
    return Template("none", 1, rng.choice(held_out(PRANKS[language], split)))


def render(
    template: Template, language: str, category: Category, rng: random.Random
) -> tuple[str, int, str | None]:
    """Fill one template and add noise. Returns (text, severity, location_text). O(L)."""
    severity = template.severity
    location: str | None = None
    text = template.text
    if category == "emergency":
        keys = ESCALATORS_BY_DEPARTMENT.get(template.department, ())
        if keys and rng.random() < P_ESCALATOR:
            text = f"{text}, {ESCALATORS[language][rng.choice(keys)]}"
            severity = min(5, severity + 1)
    if "{loc}" in text:
        vague = rng.random() < P_VAGUE_LOCATION
        location = rng.choice(VAGUE_LOCATIONS[language] if vague else LOCATIONS)
        text = text.replace("{loc}", location)
    if category == "emergency":
        if rng.random() < P_PANIC:
            panic = rng.choice(PANIC[language])
            text = f"{panic} {text}" if rng.random() < 0.5 else f"{text} {panic}"
        if language in LATIN_LANGUAGES and rng.random() < P_SHOUT:
            text = text.upper()
    if rng.random() < P_TYPO:
        text = add_typos(text, language, rng)
    return text, severity, location


def hard_row(case: HardCase, row_id: str) -> LabeledReport:
    return LabeledReport(
        id=row_id,
        text=case.text,
        language=case.language,  # type: ignore[arg-type]
        category="emergency" if case.is_emergency else "prank",
        is_emergency=case.is_emergency,
        department=case.department,  # type: ignore[arg-type]
        severity=case.severity,
        location_text=case.location_text,
        silent_sos=case.tag == "silent_sos",
        hard=case.tag,
    )


def generate_split(split: str, seen: set[str], rng: random.Random) -> list[LabeledReport]:
    """Build one split. O(n) expected; duplicates are re-drawn."""
    hard = [c for i, c in enumerate(HARD_CASES) if (i % 3 == 0) == (split == "train")]
    rows = [hard_row(c, f"{split}-h{i:02d}") for i, c in enumerate(hard)]
    seen.update(c.text for c in hard)
    for category, quota in QUOTAS[split].items():
        remaining = quota - sum(1 for r in rows if r.category == category)
        produced = 0
        while produced < remaining:
            language = LANGUAGES[produced % len(LANGUAGES)]
            template = pick_template(language, category, produced, split, rng)
            text, severity, location = render(template, language, category, rng)
            if text in seen:
                continue
            seen.add(text)
            rows.append(
                LabeledReport(
                    id=f"{split}-{len(rows):04d}",
                    text=text,
                    language=language,  # type: ignore[arg-type]
                    category=category,
                    is_emergency=category == "emergency",
                    department=template.department,  # type: ignore[arg-type]
                    severity=severity,
                    location_text=location,
                )
            )
            produced += 1
    rng.shuffle(rows)
    return rows


def mark_hidden(rows: Sequence[LabeledReport], count: int, rng: random.Random) -> list[LabeledReport]:
    hidden_ids = {r.id for r in rng.sample(list(rows), count)}
    return [r.model_copy(update={"hidden": r.id in hidden_ids}) for r in rows]


def write(rows: Sequence[LabeledReport], path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(row.model_dump_json() + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    seen: set[str] = set()
    train = generate_split("train", seen, rng)
    test = mark_hidden(generate_split("test", seen, rng), HIDDEN_TEST_ROWS, rng)
    TRAIN_PATH.parent.mkdir(parents=True, exist_ok=True)
    write(train, TRAIN_PATH)
    write(test, TEST_PATH)
    for name, rows in (("train", train), ("test", test)):
        by_cat = {c: sum(r.category == c for r in rows) for c in QUOTAS[name]}
        print(f"{name}: {len(rows)} rows {by_cat} hard={sum(r.hard is not None for r in rows)}")


if __name__ == "__main__":
    main()
