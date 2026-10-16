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
        "district": "Noida, Uttar Pradesh",
        "viewbox": (77.25, 28.43, 77.55, 28.70),
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
        body = [{"lat": "28.55", "lon": "77.35"}] if found else []
        return httpx.Response(200, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_gazetteer_places_need_no_network(db: Database) -> None:
    requests: list[httpx.Request] = []
    geo = Geocoder(nominatim(requests), db, config())
    point = await geo.geocode("सेक्टर 62")
    assert point is not None and point.source == "gazetteer" and not requests


async def test_unknown_place_queries_nominatim_once_then_caches(db: Database, tmp_path: Path) -> None:
    requests: list[httpx.Request] = []
    fake = FakeTime()
    geo = Geocoder(nominatim(requests), db, config(), clock=fake.clock, sleep=fake.sleep)
    first = await geo.geocode("Sector 44 market")
    again = await geo.geocode("sector 44  MARKET!")
    assert first is not None and first.source == "nominatim" and again == first
    assert len(requests) == 1
    params = requests[0].url.params
    assert params["bounded"] == "1" and params["viewbox"] == "77.25,28.7,77.55,28.43"
    assert params["q"] == "sector 44 market, Noida, Uttar Pradesh"
    assert requests[0].headers["user-agent"] == "Sanket-test/1.0"
    # A fresh geocoder (empty LRU) is served by the SQLite cache.
    fresh = Geocoder(nominatim(requests), db, config())
    cached = await fresh.geocode("Sector 44 market")
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
    for name in ("alpha lane", "beta lane", "gamma lane"):
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
        ("aag lagi hai Sector 18 metro ke paas", "Sector 18 metro"),
        ("सेक्टर ६२ में एक्सीडेंट", "Sector 62"),
        ("Gaur City 2 এ জল ঢুকেছে", "Gaur City 2"),
        ("sec 44 mein chori", "Sector 44"),
        ("help at the old water tank", None),
    ],
)
def test_extract_location(text: str, expected: str | None) -> None:
    assert extract_location(text) == expected


def test_normalize_and_gazetteer() -> None:
    assert normalize("  SECTOR-18, Metro!! ") == "sector 18 metro"
    assert gazetteer_lookup("Botanical Garden metro station") is not None
