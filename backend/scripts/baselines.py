"""Keyword-rules baseline: the approach most triage hackathon bots use.

Department keywords are the single words of the corpus's domain lexicon (all five
languages) that belong to exactly one department. A report is an emergency if any
keyword matches; the department with the most matches wins; severity is 4 with a
life-safety term, 3 for other emergencies, else 1. No model, no context.
"""

import re
from collections import Counter, defaultdict
from collections.abc import Sequence

from app.corpus import LEXICON
from app.decision.rules import LIFE_SAFETY
from app.models import Decision, DecisionResult

STOPWORDS = frozenset(
    "the and with near from into have has are was were people person log लोग में है का की के से को "
    "hai ka ki ke mein se ko pe par wala need needed chahiye".split()
)


def _department_keywords() -> dict[str, set[str]]:
    seen: dict[str, set[str]] = defaultdict(set)
    for by_department in LEXICON.values():
        for department, phrases in by_department.items():
            for phrase in phrases:
                for token in re.split(r"[\s,]+", phrase.lower()):
                    if len(token) >= 3 and token not in STOPWORDS:
                        seen[token].add(department)
    keywords: dict[str, set[str]] = defaultdict(set)
    for token, departments in seen.items():
        if len(departments) == 1:
            keywords[next(iter(departments))].add(token)
    return keywords


def _pattern(words: set[str]) -> re.Pattern[str]:
    latin = [rf"\b{re.escape(w)}" for w in words if w.isascii()]
    indic = [re.escape(w) for w in words if not w.isascii()]
    return re.compile("|".join(sorted(latin + indic, key=len, reverse=True)), re.IGNORECASE)


class KeywordTriage:
    def __init__(self) -> None:
        self.patterns = {department: _pattern(words) for department, words in _department_keywords().items()}

    def predict_batch(self, texts: Sequence[str]) -> list[DecisionResult]:
        """O(n·L) per department pattern."""
        results: list[DecisionResult] = []
        for text in texts:
            hits = Counter({d: len(p.findall(text)) for d, p in self.patterns.items()})
            department, count = hits.most_common(1)[0] if hits else ("none", 0)
            emergency = count > 0
            severity = 4 if emergency and LIFE_SAFETY.search(text) else (3 if emergency else 1)
            decision = Decision(
                is_emergency=emergency,
                emergency_prob=1.0 if emergency else 0.0,
                department=department if emergency else "none",  # type: ignore[arg-type]
                department_conf=1.0,
                severity=severity,
                alert_now=emergency and severity >= 4,
            )
            results.append(DecisionResult(decision=decision, source="rules", confidence=1.0, model="keyword-rules"))
        return results
