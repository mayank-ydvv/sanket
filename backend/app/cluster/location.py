"""Location normalisation, extraction and the demo-city gazetteer (Chennai).

The gazetteer lets known demo places resolve offline with no network call;
anything else goes to the geocoder's cache and then Nominatim. Every place has
its Tamil name too, matched as a word prefix because Tamil attaches case
endings to the noun ("முடிச்சூரில்" = "in Mudichur"). Coordinates are
approximate and only used for the synthetic demo.
"""

import re
from difflib import SequenceMatcher
from typing import NamedTuple


class Place(NamedTuple):
    name: str
    lat: float
    lng: float
    tamil: str


GAZETTEER: tuple[Place, ...] = (
    Place("Marina beach", 13.0500, 80.2824, "மெரினா"),
    Place("Velachery main road", 12.9790, 80.2210, "வேளச்சேரி"),
    Place("Pondy Bazaar", 13.0410, 80.2340, "பாண்டி பஜார்"),
    Place("Egmore station", 13.0780, 80.2610, "எழும்பூர்"),
    Place("Mylapore temple", 13.0339, 80.2697, "மயிலாப்பூர்"),
    Place("Anna Nagar 2nd Avenue", 13.0850, 80.2100, "அண்ணா நகர்"),
    Place("Mudichur", 12.9150, 80.0700, "முடிச்சூர்"),
    Place("Kathipara junction", 13.0070, 80.2050, "கத்திப்பாரா"),
    Place("Vadapalani Murugan temple", 13.0520, 80.2110, "வடபழனி"),
    Place("Semmozhi Poonga", 13.0510, 80.2510, "செம்மொழி பூங்கா"),
    Place("Saidapet market", 13.0210, 80.2230, "சைதாப்பேட்டை"),
    Place("Adyar bridge", 13.0130, 80.2560, "அடையாறு"),
    Place("Koyambedu market", 13.0700, 80.1950, "கோயம்பேடு"),
    Place("Ganesapuram subway", 13.1130, 80.2580, "கணேசபுரம்"),
    Place("Porur junction", 13.0350, 80.1580, "போரூர்"),
    Place("Pallikaranai", 12.9350, 80.2130, "பள்ளிக்கரணை"),
    Place("Sowcarpet market", 13.0920, 80.2820, "சௌகார்பேட்டை"),
    Place("Ashok Nagar", 13.0370, 80.2120, "அசோக் நகர்"),
)

_DIGITS = str.maketrans("०१२३४५६७८९০১২৩৪৫৬৭৮৯௦௧௨௩௪௫௬௭௮௯", "0123456789" * 3)
# Keep Indic letters *and* their combining vowel signs (U+0900–U+0DFF), which \w alone drops.
_PUNCT = re.compile(r"[^\w\sऀ-෿]")
_SPACES = re.compile(r"\s+")
_DIGIT_RUNS = re.compile(r"\d+")
_WORD_BEFORE = r"(?<![\wऀ-෿])"
_TAMIL_VIRAMA = "்"
FUZZY_RATIO = 0.85


def normalize(text: str) -> str:
    """Lowercase, ASCII digits, no punctuation. O(L)."""
    return _SPACES.sub(" ", _PUNCT.sub(" ", text.translate(_DIGITS).lower())).strip()


def _pattern(key: str) -> str:
    """Whole words for Latin names; a word prefix for Tamil ones, whose last
    consonant loses its virama when a case ending is added."""
    if key.isascii():
        return rf"{_WORD_BEFORE}{re.escape(key)}(?![\wऀ-෿])"
    return _WORD_BEFORE + re.escape(key.removesuffix(_TAMIL_VIRAMA))


_BY_KEY: dict[str, Place] = {}
for _place in GAZETTEER:
    _BY_KEY[normalize(_place.name)] = _place
    _BY_KEY[normalize(_place.tamil)] = _place
# Longest names first so "anna nagar 2nd avenue" wins over a shorter overlapping name.
_KEYS = sorted(_BY_KEY, key=len, reverse=True)
_LANDMARKS = re.compile("|".join(f"({_pattern(k)})" for k in _KEYS))
_LATIN_KEYS = {k: p for k, p in _BY_KEY.items() if k.isascii()}


def _landmark(key: str) -> Place | None:
    match = _LANDMARKS.search(key)
    return _BY_KEY[_KEYS[match.lastindex - 1]] if match and match.lastindex else None


def _fuzzy_landmark(key: str) -> Place | None:
    """Latin gazetteer name matching a same-length token window despite typos.

    O(G·T) similarity checks for G gazetteer names and T tokens; only runs when
    the exact alternation found nothing.
    """
    tokens = key.split()
    best: tuple[float, Place] | None = None
    for name, place in _LATIN_KEYS.items():
        width = len(name.split())
        for start in range(max(1, len(tokens) - width + 1)):
            window = " ".join(tokens[start : start + width])
            if not window or not set(window[:3]) & set(name[:3]):
                continue
            if _DIGIT_RUNS.findall(window) != _DIGIT_RUNS.findall(name):
                continue  # typos bend letters, never numbers: 3rd Avenue is not 2nd
            ratio = SequenceMatcher(None, window, name).ratio()
            if ratio >= FUZZY_RATIO and (best is None or ratio > best[0]):
                best = (ratio, place)
    return best[1] if best else None


def gazetteer_lookup(location_text: str) -> Place | None:
    """Known demo place mentioned in a location string (English or Tamil), tolerating typos."""
    key = normalize(location_text)
    return _BY_KEY.get(key) or _landmark(key) or _fuzzy_landmark(key)


def extract_location(text: str) -> str | None:
    """Canonical name of the best known place mentioned in free text. O(L) + fuzzy fallback."""
    place = gazetteer_lookup(text)
    return place.name if place else None
