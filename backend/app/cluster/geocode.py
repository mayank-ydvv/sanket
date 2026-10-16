"""Geocoding: gazetteer -> in-memory LRU -> SQLite cache -> Nominatim (1 req/s, bounded).

Nominatim's usage policy allows at most one request per second with an
identifying User-Agent, so every network lookup goes through one global limiter.
When the limiter's queue would exceed ``max_wait_s`` the lookup is skipped (not
cached) and the report stays "location unconfirmed" instead of stalling triage.
"""

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

import httpx

from app.cluster.location import gazetteer_lookup, normalize
from app.db import Database

log = logging.getLogger(__name__)

NOMINATIM_INTERVAL_S = 1.0
GeoSource = Literal["gazetteer", "cache", "nominatim"]


@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lng: float
    source: GeoSource


@dataclass(frozen=True)
class GeocoderConfig:
    url: str
    user_agent: str
    district: str
    viewbox: tuple[float, float, float, float]  # west, south, east, north
    max_wait_s: float
    network: bool = True


class Geocoder:
    def __init__(
        self,
        http: httpx.AsyncClient,
        db: Database,
        config: GeocoderConfig,
        lru_size: int = 4096,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._http = http
        self._db = db
        self._config = config
        self._lru: OrderedDict[str, GeoPoint | None] = OrderedDict()
        self._lru_size = lru_size
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._next_slot = 0.0
        self._waiting = 0
        self.network_calls = 0

    async def geocode(self, location_text: str | None) -> GeoPoint | None:
        """Resolve a place mention. O(L) plus at most one rate-limited network call."""
        if not location_text:
            return None
        query = normalize(location_text)
        if not query:
            return None
        place = gazetteer_lookup(query)
        if place is not None:
            return GeoPoint(place.lat, place.lng, "gazetteer")
        if query in self._lru:
            self._lru.move_to_end(query)
            return self._lru[query]
        cached = await self._db.geocode_cache_get(query)
        if cached is not None:
            point = GeoPoint(cached[0], cached[1], "cache") if cached[0] is not None else None
            self._remember(query, point)
            return point
        if not self._config.network:
            return None
        return await self._nominatim(query)

    def _remember(self, query: str, point: GeoPoint | None) -> None:
        self._lru[query] = point
        self._lru.move_to_end(query)
        if len(self._lru) > self._lru_size:
            self._lru.popitem(last=False)

    async def _nominatim(self, query: str) -> GeoPoint | None:
        if self._waiting * NOMINATIM_INTERVAL_S > self._config.max_wait_s:
            return None
        self._waiting += 1
        try:
            async with self._lock:
                delay = self._next_slot - self._clock()
                if delay > 0:
                    await self._sleep(delay)
                self._next_slot = self._clock() + NOMINATIM_INTERVAL_S
                point, cacheable = await self._request(query)
        finally:
            self._waiting -= 1
        if cacheable:
            self._remember(query, point)
            async with self._db.transaction():
                await self._db.geocode_cache_put(
                    query, point.lat if point else None, point.lng if point else None
                )
        return point

    async def _request(self, query: str) -> tuple[GeoPoint | None, bool]:
        """One Nominatim search. Returns (point, cacheable); failures are not cached."""
        cfg = self._config
        west, south, east, north = cfg.viewbox
        self.network_calls += 1
        try:
            response = await self._http.get(
                cfg.url,
                params={
                    "q": f"{query}, {cfg.district}",
                    "format": "jsonv2",
                    "limit": 1,
                    "countrycodes": "in",
                    "viewbox": f"{west},{north},{east},{south}",
                    "bounded": 1,
                },
                headers={"User-Agent": cfg.user_agent},
                timeout=5.0,
            )
            response.raise_for_status()
            results = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("nominatim lookup failed for %r: %r", query, exc)
            return None, False
        if not results:
            return None, True
        return GeoPoint(float(results[0]["lat"]), float(results[0]["lon"]), "nominatim"), True
