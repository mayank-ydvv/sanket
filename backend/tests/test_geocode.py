from pathlib import Path

import httpx
import pytest

from app.cluster.geocode import Geocoder, GeocoderConfig
from app.cluster.location import extract_location, gazetteer_lookup, normalize
from app.db import Database


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def config(**overrides: object) -> GeocoderConfig:
    base: dict[str, object] = {
        "url": "https://nominatim.test/search",
        "user_agent": "Sanket-test/1.0",
        "district": "Chennai, Tamil Nadu",
        "viewbox": (80.05, 12.85, 80.33, 13.25),
        "max_wait_s": 10.0,
    }
    return GeocoderConfig(**(base | overrides))  # type: ignore[arg-type]


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    database = await Database.open(tmp_path / "geo.db")
    yield database  # type: ignore[misc]
    await database.close()


def nominatim(requests: list[httpx.Request], found: bool = True) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = [{"lat": "13.06", "lon": "80.24", "display_name": "Lane, Nungambakkam, Chennai"}] if found else []
        return httpx.Response(200, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_gazetteer_places_need_no_network(db: Database) -> None:
    requests: list[httpx.Request] = []
    geo = Geocoder(nominatim(requests), db, config())
    point = await geo.geocode("முடிச்சூரில்")
    assert point is not None and point.source == "gazetteer" and not requests


async def test_unknown_place_queries_nominatim_once_then_caches(db: Database, tmp_path: Path) -> None:
    requests: list[httpx.Request] = []
    fake = FakeTime()
    geo = Geocoder(nominatim(requests), db, config(), clock=fake.clock, sleep=fake.sleep)
    first = await geo.geocode("Nungambakkam lane")
    again = await geo.geocode("nungambakkam  LANE!")
    assert first is not None and first.source == "nominatim" and again == first
    assert len(requests) == 1
    params = requests[0].url.params
    assert params["bounded"] == "1" and params["viewbox"] == "80.05,13.25,80.33,12.85"
    assert params["q"] == "nungambakkam lane, Chennai, Tamil Nadu"
    assert requests[0].headers["user-agent"] == "Sanket-test/1.0"
    # A fresh geocoder (empty LRU) is served by the SQLite cache.
    fresh = Geocoder(nominatim(requests), db, config())
    cached = await fresh.geocode("Nungambakkam lane")
    assert cached is not None and cached.source == "cache" and len(requests) == 1


async def test_misses_are_cached_too(db: Database) -> None:
    requests: list[httpx.Request] = []
    geo = Geocoder(nominatim(requests, found=False), db, config())
    assert await geo.geocode("nowhere special") is None
    assert await geo.geocode("nowhere special") is None
    assert len(requests) == 1


async def test_one_request_per_second(db: Database) -> None:
    requests: list[httpx.Request] = []
    fake = FakeTime()
    geo = Geocoder(nominatim(requests), db, config(), clock=fake.clock, sleep=fake.sleep)
    for name in ("alpha lane", "beta lane", "gamma lane"):  # "lane" matches the fake display_name
        await geo.geocode(name)
    assert len(requests) == 3
    assert fake.slept == [1.0, 1.0]


async def test_long_queue_skips_lookup_instead_of_stalling(db: Database) -> None:
    requests: list[httpx.Request] = []
    geo = Geocoder(nominatim(requests), db, config(max_wait_s=0.0))
    geo._waiting = 1  # simulate a lookup already queued  # noqa: SLF001
    assert await geo.geocode("delta lane") is None and not requests


async def test_network_disabled(db: Database) -> None:
    requests: list[httpx.Request] = []
    geo = Geocoder(nominatim(requests), db, config(network=False))
    assert await geo.geocode("epsilon lane") is None and not requests


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("aag lagi hai Marina beach ke paas", "Marina beach"),
        ("Velachery main road पर एक्सीडेंट", "Velachery main road"),
        ("முடிச்சூரில் வெள்ளம், மக்கள் மாடியில்", "Mudichur"),  # Tamil case ending on the name
        ("கத்திப்பாராவில் விபத்து", "Kathipara junction"),
        ("அண்ணா நகர் 2வது அவென்யூவில் தீ", "Anna Nagar 2nd Avenue"),
        ("Anna Nagar 2nd Avenue এ জল ঢুকেছে", "Anna Nagar 2nd Avenue"),
        ("help at the old water tank", None),
    ],
)
def test_extract_location(text: str, expected: str | None) -> None:
    assert extract_location(text) == expected


def test_normalize_and_gazetteer() -> None:
    assert normalize("  MARINA-Beach, ௨!! ") == "marina beach 2"
    assert gazetteer_lookup("Egmore station station") is not None


@pytest.mark.parametrize(
    ("typo", "place"),
    [
        ("saidapet markt", "Saidapet market"),
        ("marina beech", "Marina beach"),
        ("egmore staton", "Egmore station"),
        ("vadapalni murugan temple", "Vadapalani Murugan temple"),
    ],
)
def test_gazetteer_tolerates_typos(typo: str, place: str) -> None:
    found = gazetteer_lookup(typo)
    assert found is not None and found.name == place


def test_normalize_keeps_indic_vowel_signs() -> None:
    assert normalize("மூன்றாவது மாடியில்!") == "மூன்றாவது மாடியில்"
    assert normalize("घर में") == "घर में"


async def test_nominatim_hit_sharing_no_token_with_query_is_rejected(db: Database) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"lat": "13.05", "lon": "80.28", "display_name": "Marina beach, Chennai, Tamil Nadu"}])

    geo = Geocoder(httpx.AsyncClient(transport=httpx.MockTransport(handler)), db, config())
    assert await geo.geocode("மூன்றாவது மாடியில்") is None  # "on the 3rd floor" is not a place


def test_fuzzy_match_never_changes_numbers() -> None:
    assert gazetteer_lookup("Anna Nagar 3rd Avenue") is None  # 3rd is not 2nd
    assert extract_location("aag lagi anna nagar 3rd avenue mein") is None


async def test_generic_place_words_alone_are_not_a_location(db: Database) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"lat": "13.1", "lon": "80.2", "display_name": "Ashok Colony, Perambur"}])

    geo = Geocoder(httpx.AsyncClient(transport=httpx.MockTransport(handler)), db, config())
    assert await geo.geocode("colony") is None
    assert await geo.geocode("ashok colony") is not None
