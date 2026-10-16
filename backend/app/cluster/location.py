"""Location normalisation, extraction and the demo-district gazetteer (Noida).

The gazetteer lets known demo places resolve offline with no network call;
anything else goes to the geocoder's cache and then Nominatim. Coordinates are
approximate and only used for the synthetic demo.
"""

import re
from difflib import SequenceMatcher
from typing import NamedTuple


class Place(NamedTuple):
    name: str
    lat: float
    lng: float


GAZETTEER: tuple[Place, ...] = (
    Place("Sector 18 metro", 28.5708, 77.3261),
    Place("Sector 62", 28.6270, 77.3650),
    Place("Atta market", 28.5672, 77.3236),
    Place("Botanical Garden metro", 28.5641, 77.3341),
    Place("Sector 15 gurudwara", 28.5850, 77.3110),
    Place("Gaur City 2", 28.6154, 77.4300),
    Place("Sector 137", 28.5100, 77.4040),
    Place("Pari Chowk", 28.4670, 77.5130),
    Place("Rajendra Nagar Shiv mandir", 28.6740, 77.3510),
    Place("Sector 50 park", 28.5700, 77.3640),
    Place("Sector 76", 28.5660, 77.3850),
    Place("Film City", 28.5770, 77.3170),
    Place("Sector 22 market", 28.5980, 77.3420),
    Place("Sector 93 expressway", 28.5240, 77.3830),
    Place("Sector 104 crossing", 28.5420, 77.3730),
    Place("Kalindi Kunj bridge", 28.5460, 77.3110),
    Place("Sector 12 market", 28.5980, 77.3320),
    Place("Mamura chowk", 28.6060, 77.3740),
)

_DIGITS = str.maketrans("०१२३४५६७८९০১২৩৪৫৬৭৮৯௦௧௨௩௪௫௬௭௮௯", "0123456789" * 3)
_SECTOR_WORDS = re.compile(r"सेक्टर|सैक्टर|সেক্টর|செக்டர்|sec(?:tor|\.)?(?=\s*\d)", re.IGNORECASE)
# Keep Indic letters *and* their combining vowel signs (U+0900–U+0DFF), which \w alone drops.
_PUNCT = re.compile(r"[^\w\s\u0900-\u0DFF]")
_SPACES = re.compile(r"\s+")
_SECTOR = re.compile(r"\bsector\s*(\d{1,3})\b")
# Misspelt "sector" ("secor 76", "sectoor 18"): an s-word close to "sector" before a number.
_SECTOR_LIKE = re.compile(r"\b(s[a-z]{2,8})\s*(\d{1,3})\b")
_DIGIT_RUNS = re.compile(r"\d+")
FUZZY_RATIO = 0.85
SECTOR_WORD_RATIO = 0.6


def normalize(text: str) -> str:
    """Lowercase, ASCII digits, one spelling of 'sector', no punctuation. O(L)."""
    text = _SECTOR_WORDS.sub("sector ", text.translate(_DIGITS))
    return _SPACES.sub(" ", _PUNCT.sub(" ", text.lower())).strip()


_BY_KEY: dict[str, Place] = {normalize(p.name): p for p in GAZETTEER}
# Longest names first so "sector 18 metro" wins over a bare "sector 18".
_LANDMARKS = re.compile(
    "|".join(rf"\b{re.escape(k)}\b" for k in sorted(_BY_KEY, key=len, reverse=True))
)
_SECTOR_PLACES: dict[str, Place] = {}
for _place in GAZETTEER:
    _match = _SECTOR.search(normalize(_place.name))
    if _match:
        _SECTOR_PLACES.setdefault(_match.group(1), _place)


def _sector_number(key: str) -> str | None:
    match = _SECTOR.search(key)
    if match:
        return match.group(1)
    for word, number in _SECTOR_LIKE.findall(key):
        if SequenceMatcher(None, word, "sector").ratio() >= SECTOR_WORD_RATIO:
            return number
    return None


def _fuzzy_landmark(key: str) -> Place | None:
    """Gazetteer name matching a same-length token window despite typos.

    O(G·T) similarity checks for G gazetteer names and T tokens; only runs when
    the exact alternation found nothing.
    """
    tokens = key.split()
    best: tuple[float, Place] | None = None
    for name, place in _BY_KEY.items():
        width = len(name.split())
        for start in range(max(1, len(tokens) - width + 1)):
            window = " ".join(tokens[start : start + width])
            if not window or not set(window[:3]) & set(name[:3]):
                continue
            if _DIGIT_RUNS.findall(window) != _DIGIT_RUNS.findall(name):
                continue  # typos bend letters, never sector numbers: 44 is not 22
            ratio = SequenceMatcher(None, window, name).ratio()
            if ratio >= FUZZY_RATIO and (best is None or ratio > best[0]):
                best = (ratio, place)
    return best[1] if best else None


def gazetteer_lookup(location_text: str) -> Place | None:
    """Known demo place mentioned in a location string, tolerating typos. O(L) + fuzzy fallback."""
    key = normalize(location_text)
    if key in _BY_KEY:
        return _BY_KEY[key]
    match = _LANDMARKS.search(key)
    if match:
        return _BY_KEY[match.group(0)]
    fuzzy = _fuzzy_landmark(key)
    if fuzzy is not None:
        return fuzzy
    number = _sector_number(key)
    return _SECTOR_PLACES.get(number) if number else None


def extract_location(text: str) -> str | None:
    """Best place mention in free text: a known landmark, else 'Sector N'. O(L) + fuzzy fallback."""
    key = normalize(text)
    match = _LANDMARKS.search(key)
    if match:
        return _BY_KEY[match.group(0)].name
    fuzzy = _fuzzy_landmark(key)
    if fuzzy is not None:
        return fuzzy.name
    number = _sector_number(key)
    return f"Sector {number}" if number else None
