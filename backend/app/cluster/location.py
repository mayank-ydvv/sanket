"""Location normalisation, extraction and the demo-district gazetteer (Noida).

The gazetteer lets known demo places resolve offline with no network call;
anything else goes to the geocoder's cache and then Nominatim. Coordinates are
approximate and only used for the synthetic demo.
"""

import re
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
_PUNCT = re.compile(r"[^\w\s]")
_SPACES = re.compile(r"\s+")
_SECTOR = re.compile(r"\bsector\s*(\d{1,3})\b")


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


def gazetteer_lookup(location_text: str) -> Place | None:
    """Known demo place mentioned in a location string. O(L) via one alternation."""
    key = normalize(location_text)
    if key in _BY_KEY:
        return _BY_KEY[key]
    match = _LANDMARKS.search(key)
    if match:
        return _BY_KEY[match.group(0)]
    sector = _SECTOR.search(key)
    return _SECTOR_PLACES.get(sector.group(1)) if sector else None


def extract_location(text: str) -> str | None:
    """Best place mention in free text: a known landmark, else 'Sector N'. O(L)."""
    key = normalize(text)
    match = _LANDMARKS.search(key)
    if match:
        return _BY_KEY[match.group(0)].name
    sector = _SECTOR.search(key)
    return f"Sector {sector.group(1)}" if sector else None
