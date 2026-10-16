"""Safety rules. They run last on every report and can only raise severity or add review flags.

Each keyword group is one precompiled alternation, so a report is scanned once
per group: O(L) per group in practice, independent of how many reports exist.
Latin-script terms use word boundaries; Indic-script terms are matched as
substrings (``\\b`` is unreliable around combining vowel signs).
"""

import re
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from app.models import Channel, Decision, Department

SEVERITY_FLOOR = 3
SILENT_SOS_SEVERITY = 4
GIBBERISH_MIN_TOKENS = 3
GIBBERISH_RATIO = 0.6
PRANK_FLAG_AT = 0.5


def _compile(latin: Iterable[str], indic: Iterable[str] = ()) -> re.Pattern[str]:
    parts = [rf"\b(?:{term})\b" for term in latin] + list(indic)
    return re.compile("|".join(parts), re.IGNORECASE)


LIFE_SAFETY = _compile(
    latin=(
        r"breath(?:e|ing)?", r"unconscious", r"faint(?:ed)?", r"bleed(?:ing)?", r"blood",
        r"chest pain", r"heart attack", r"child(?:ren)?", r"kids?", r"baby", r"trapped",
        r"stuck inside", r"fire", r"flames?", r"drown(?:ing)?", r"collapsed?", r"not waking up",
        # Hinglish
        r"saans", r"behosh", r"khoon", r"seene mein dard", r"dil ka daura", r"bach+h?(?:a|i|e)",
        r"phans[ea]?", r"phas[ai]", r"aag", r"doob", r"lapte",
    ),
    indic=(
        # Hindi
        "सांस", "साँस", "बेहोश", "खून", "सीने में दर्द", "दिल का दौरा", "बच्च", "फंस", "फँस", "आग",
        "डूब", "लपट",
        # Tamil (தீ alone is a prefix of unrelated words, so it needs a terminator)
        "மூச்சு", "மயக்க", "ரத்த", "நெஞ்சு வலி", "மாரடைப்பு", "குழந்தை", "சிக்கி", r"தீ(?=[\s,.!?]|$)",
        "தீப்பிடி", "தீப்பிழம்பு", "மூழ்க",
        # Bengali
        "শ্বাস", "অজ্ঞান", "রক্ত", "বুকে ব্যথা", "হার্ট অ্যাটাক", "বাচ্চা", "শিশু", "আটকে", "আগুন",
        "ডুবে",
    ),
)

# Details that escalate a whole incident (report: children, trapped people, fire spreading).
ESCALATION = _compile(
    latin=(
        r"trapped", r"stuck inside", r"child(?:ren)?", r"kids?", r"baby", r"spreading",
        r"phans[ea]?", r"phas[ai]", r"bach+h?(?:a|i|e)", r"fail rahi",
    ),
    indic=("फंस", "फँस", "बच्च", "फैल", "சிக்கி", "குழந்தை", "பரவு", "আটকে", "বাচ্চা", "শিশু", "ছড়া"),
)

COERCED_SPEECH = _compile(
    latin=(
        r"can'?t talk", r"cannot talk", r"can'?t speak", r"cannot speak", r"bol nahi sakt[ai]",
        r"baat nahi kar sakt[ai]",
    ),
    indic=("बोल नहीं सकत", "बात नहीं कर सकत", "பேச முடியாது", "কথা বলতে পারছি না"),
)

LAUGHTER = _compile(
    latin=(r"lol+", r"ha(?:ha)+h?", r"just kidding", r"jk", r"mazaak", r"mazak", r"prank"),
    indic=("हाहा", "मज़ाक", "मजाक", "ஹாஹா", "விளையாட்டுக்கு", "হাহা", "মজা করছিলাম"),
)

HAZARDS: dict[str, re.Pattern[str]] = {
    "fire": _compile(
        (r"fire", r"flames?", r"burning", r"aag", r"lapte"),
        ("आग", "लपट", r"தீ(?=[\s,.!?]|$)", "தீப்பிடி", "தீப்பிழம்பு", "আগুন"),
    ),
    "smoke": _compile((r"smoke", r"dhua+n", r"dhuan"), ("धुआं", "धुँआ", "புகை", "ধোঁয়া")),
    "gas": _compile((r"gas",), ("गैस", "கேஸ்", "গ্যাস")),
    "flood_water": _compile(
        (r"flood(?:ed|ing)?", r"water logging", r"baadh", r"paani bhar"),
        ("बाढ़", "पानी भर", "வெள்ள", "বন্যা", "জল ঢুক"),
    ),
    "electrical": _compile(
        (r"live wire", r"electric", r"transformer", r"spark(?:ing|s)?", r"current", r"bijli"),
        ("बिजली", "करंट", "ट्रांसफार्मर", "மின்", "டிரான்ஸ்பார்மர்", "বিদ্যুৎ", "ট্রান্সফরমার", "কারেন্ট"),
    ),
    "structural_collapse": _compile(
        (r"collapsed?", r"crack(?:ing|ed)?", r"deewar gir", r"building gir"),
        ("दीवार गिर", "इमारत गिर", "मकान गिर", "बिल्डिंग गिर", "दरार", "இடிந்", "விரிசல்", "ভেঙে", "ফাটল"),
    ),
    "weapon": _compile((r"knife", r"knives", r"gun(?:shots?)?", r"chaku", r"goli"),
                       ("चाकू", "गोली", "கத்தி", "துப்பாக்கி", "ছুরি", "গুলি")),
}

_TAP_CODE = re.compile(r"^[\s\d#*+.,\-]+$")
_MORSE = re.compile(r"^[\s.\-_/·•]+$")
_LATIN_WORD = re.compile(r"[a-z]+")
_VOWELS = frozenset("aeiouy")
_CONSONANT_RUN = re.compile(r"[b-df-hj-np-tv-xz]{4,}")


def _is_gibberish(text: str) -> bool:
    """Latin keyboard-mash heuristic: most tokens lack vowels or have 4+ consonant runs. O(L)."""
    tokens = _LATIN_WORD.findall(text.lower())
    if len(tokens) < GIBBERISH_MIN_TOKENS or any(not ch.isascii() for ch in text if ch.isalpha()):
        return False
    odd = sum(1 for t in tokens if not (_VOWELS & set(t)) or _CONSONANT_RUN.search(t))
    return odd / len(tokens) >= GIBBERISH_RATIO


def silent_sos_signal(text: str, channel: Channel) -> str | None:
    """Name of the silent-SOS pattern a report matches, or None. O(L)."""
    stripped = text.strip()
    if not stripped:
        return "empty_call" if channel == "call" else "empty_report"
    if _TAP_CODE.match(stripped) and sum(ch.isdigit() for ch in stripped) >= 3:
        return "tap_code"
    if _MORSE.match(stripped) and len(stripped.replace(" ", "")) >= 3:
        return "morse"
    if COERCED_SPEECH.search(stripped):
        return "coerced_speech"
    if _is_gibberish(stripped):
        return "gibberish"
    return None


def detect_hazards(text: str) -> list[str]:
    """Canonical hazard names mentioned in the text. O(L) per hazard group."""
    return [name for name, pattern in HAZARDS.items() if pattern.search(text)]


class PrankTracker:
    """Per-caller sliding window of recent departments. O(1) amortised per report.

    Callers are kept in an LRU map capped at ``max_callers`` so memory stays bounded.
    """

    def __init__(
        self,
        window_s: float,
        min_reports: int,
        clock: Callable[[], float] = time.time,
        max_callers: int = 50_000,
    ) -> None:
        self._window_s = window_s
        self._min_reports = min_reports
        self._clock = clock
        self._max_callers = max_callers
        self._history: OrderedDict[str, deque[tuple[float, Department]]] = OrderedDict()

    def observe(self, caller_hash: str | None, department: Department) -> float:
        """Record one report and return the caller's repeat/contradiction score in [0, 1]."""
        if caller_hash is None:
            return 0.0
        now = self._clock()
        history = self._history.pop(caller_hash, None) or deque()
        while history and now - history[0][0] > self._window_s:
            history.popleft()
        history.append((now, department))
        self._history[caller_hash] = history
        if len(self._history) > self._max_callers:
            self._history.popitem(last=False)
        if len(history) <= self._min_reports:
            return 0.0
        departments = {d for _, d in history if d != "none"}
        if len(departments) < 2:
            return 0.0
        excess = len(history) - self._min_reports
        return min(1.0, 0.3 + 0.1 * excess + 0.2 * (len(departments) - 1))


@dataclass(frozen=True)
class RuleOutcome:
    decision: Decision
    fired: list[str]


class SafetyRules:
    """Applies every rule to one decision. Never lowers severity, never dismisses."""

    def __init__(self, pranks: PrankTracker) -> None:
        self._pranks = pranks

    def apply(
        self,
        text: str,
        channel: Channel,
        caller_hash: str | None,
        decision: Decision,
        prior_prank: float | None = None,
    ) -> RuleOutcome:
        """O(L) per report: one pass per keyword group.

        ``prior_prank`` re-applies the rules to a revised decision without counting
        the caller a second time in the repeat-caller window.
        """
        fired: list[str] = []
        update: dict[str, object] = {}
        severity = decision.severity
        review = decision.needs_human_review

        signal = silent_sos_signal(text, channel)
        if signal is not None:
            fired.append(f"silent_sos:{signal}")
            update |= {
                "silent_sos": True,
                "is_emergency": True,
                "emergency_prob": max(decision.emergency_prob, 0.9),
                "department": "police",
                "alert_now": True,
            }
            severity = max(severity, SILENT_SOS_SEVERITY)
            review = True

        if severity < SEVERITY_FLOOR and LIFE_SAFETY.search(text):
            fired.append("severity_floor")
            severity = SEVERITY_FLOOR
            if not decision.is_emergency:
                review = True

        hazards = detect_hazards(text)
        merged_hazards = list(dict.fromkeys([*decision.hazards, *hazards]))
        if merged_hazards != decision.hazards:
            update["hazards"] = merged_hazards

        observed = (
            prior_prank if prior_prank is not None else self._pranks.observe(caller_hash, decision.department)
        )
        prank = max(decision.prank_score, observed)
        if LAUGHTER.search(text):
            prank = max(prank, 0.6)
        if prank > decision.prank_score:
            update["prank_score"] = prank
        if prank >= PRANK_FLAG_AT:
            fired.append("prank_suspected")

        update |= {"severity": severity, "needs_human_review": review}
        return RuleOutcome(decision=decision.model_copy(update=update), fired=fired)
