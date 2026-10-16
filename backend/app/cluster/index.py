"""Spatial-temporal incident index. A report is never compared with every incident.

* Located reports look up their ~1 km grid cell and its 8 neighbours (which
  together cover the join radius), then keep candidates within ``radius_km`` by
  haversine. Unlocated incidents of the same department are added from a
  bounded recency list.
* Unlocated reports compare against the ``unlocated_k`` most recently updated
  open incidents of the same department.
* Candidates are scored with one (k × d) @ d matrix-vector product over unit
  centroids, plus a small bonus for the same department.
* After a join moves an incident's centroid or location, the same lookup finds
  any "twin" incident it now matches (typically one started by an unlocated
  report) so the two can be merged.
* Only incidents updated within ``window_s`` stay in the index; expiry uses a
  min-heap of (last_updated, id) with lazy deletion of stale entries.

So a lookup is O(k·d) for k candidates, with k bounded by local density, not by
the total number of incidents n; updates are O(d + log n).
"""

import heapq
import math
import time
from collections import OrderedDict, defaultdict
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

Vector = npt.NDArray[np.float32]
Cell = tuple[int, int]
KM_PER_DEG_LAT = 111.32
EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance. O(1)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def _unit(vector: Vector) -> Vector:
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 0 else vector


@dataclass
class IndexedIncident:
    id: str
    department: str
    vector_sum: Vector
    centroid: Vector
    count: int
    last_updated: float
    lat: float | None = None
    lng: float | None = None
    located_count: int = 0
    cell: Cell | None = None


@dataclass(frozen=True)
class Match:
    incident_id: str
    score: float


class IncidentIndex:
    def __init__(
        self,
        center_lat: float,
        radius_km: float,
        window_s: float,
        similarity: float,
        department_bonus: float,
        unlocated_k: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._dlat = radius_km / KM_PER_DEG_LAT
        self._dlng = radius_km / (KM_PER_DEG_LAT * math.cos(math.radians(center_lat)))
        self._radius_km = radius_km
        self._window_s = window_s
        self._similarity = similarity
        self._bonus = department_bonus
        self._unlocated_k = unlocated_k
        self._clock = clock
        self._incidents: dict[str, IndexedIncident] = {}
        self._cells: dict[Cell, set[str]] = defaultdict(set)
        self._recent: dict[str, OrderedDict[str, None]] = defaultdict(OrderedDict)
        self._recent_unlocated: dict[str, OrderedDict[str, None]] = defaultdict(OrderedDict)
        self._heap: list[tuple[float, str]] = []

    def __len__(self) -> int:
        return len(self._incidents)

    @property
    def window_s(self) -> float:
        return self._window_s

    def __contains__(self, incident_id: object) -> bool:
        return incident_id in self._incidents

    def get(self, incident_id: str) -> IndexedIncident | None:
        return self._incidents.get(incident_id)

    def cell_of(self, lat: float, lng: float) -> Cell:
        return math.floor(lat / self._dlat), math.floor(lng / self._dlng)

    # -- lookup ---------------------------------------------------------------

    def candidates(self, department: str, lat: float | None, lng: float | None) -> list[IndexedIncident]:
        """Bounded candidate set for one report. O(k)."""
        self.expire()
        seen: dict[str, IndexedIncident] = {}
        if lat is not None and lng is not None:
            ci, cj = self.cell_of(lat, lng)
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    for incident_id in self._cells.get((ci + di, cj + dj), ()):
                        inc = self._incidents[incident_id]
                        if haversine_km(lat, lng, inc.lat, inc.lng) <= self._radius_km:  # type: ignore[arg-type]
                            seen[incident_id] = inc
            pool = self._recent_unlocated.get(department)
        else:
            pool = self._recent.get(department)
        if pool:
            for taken, incident_id in enumerate(reversed(pool)):
                if taken >= self._unlocated_k:
                    break
                seen.setdefault(incident_id, self._incidents[incident_id])
        return list(seen.values())

    def best_match(
        self, vector: Vector, department: str, lat: float | None, lng: float | None
    ) -> Match | None:
        """Highest-scoring candidate above the join threshold. O(k·d)."""
        candidates = self.candidates(department, lat, lng)
        if not candidates:
            return None
        centroids = np.stack([c.centroid for c in candidates])
        scores = centroids @ vector
        bonus = np.fromiter((c.department == department for c in candidates), dtype=np.float32, count=len(candidates))
        scores = scores + self._bonus * bonus
        best = int(np.argmax(scores))
        if float(scores[best]) < self._similarity:
            return None
        return Match(candidates[best].id, float(scores[best]))

    def find_twin(self, incident_id: str) -> Match | None:
        """Another open incident this one now matches at the join threshold. O(k·d)."""
        inc = self._incidents[incident_id]
        candidates = [
            c for c in self.candidates(inc.department, inc.lat, inc.lng) if c.id != incident_id
        ]
        if not candidates:
            return None
        scores = np.stack([c.centroid for c in candidates]) @ inc.centroid
        bonus = np.fromiter((c.department == inc.department for c in candidates), dtype=np.float32, count=len(candidates))
        scores = scores + self._bonus * bonus
        best = int(np.argmax(scores))
        if float(scores[best]) < self._similarity:
            return None
        return Match(candidates[best].id, float(scores[best]))

    def merge(self, keep_id: str, gone_id: str) -> IndexedIncident:
        """Absorb ``gone_id`` into ``keep_id`` (vectors, counts, location). O(d + log n)."""
        keep, gone = self._incidents[keep_id], self._incidents[gone_id]
        keep.vector_sum = keep.vector_sum + gone.vector_sum
        keep.centroid = _unit(keep.vector_sum)
        keep.count += gone.count
        if gone.lat is not None and gone.lng is not None and gone.located_count:
            self._set_location(keep, gone.lat, gone.lng, weight=gone.located_count)
        self.drop(gone_id)
        self._touch(keep, max(keep.last_updated, gone.last_updated))
        return keep

    # -- updates --------------------------------------------------------------

    def add(
        self,
        incident_id: str,
        vector: Vector,
        department: str,
        lat: float | None,
        lng: float | None,
        count: int = 1,
        updated_at: float | None = None,
    ) -> IndexedIncident:
        """Insert a new incident (or restore one with ``count`` reports). O(d + log n)."""
        now = self._clock() if updated_at is None else updated_at
        vector_sum = (vector * count).astype(np.float32)
        inc = IndexedIncident(incident_id, department, vector_sum, _unit(vector_sum), count, now)
        self._incidents[incident_id] = inc
        if lat is not None and lng is not None:
            self._set_location(inc, lat, lng, weight=count)
        self._touch(inc, now)
        return inc

    def join(
        self, incident_id: str, vector: Vector, lat: float | None, lng: float | None
    ) -> IndexedIncident:
        """Add one report: running-sum centroid (renormalised), running-mean location. O(d + log n)."""
        inc = self._incidents[incident_id]
        inc.vector_sum = inc.vector_sum + vector
        inc.centroid = _unit(inc.vector_sum)
        inc.count += 1
        if lat is not None and lng is not None:
            self._set_location(inc, lat, lng, weight=1)
        self._touch(inc, self._clock())
        return inc

    def remove_report(self, incident_id: str, vector: Vector) -> IndexedIncident | None:
        """Take one report's vector back out (used by split). O(d)."""
        inc = self._incidents.get(incident_id)
        if inc is None:
            return None
        if inc.count <= 1:
            self.drop(incident_id)
            return None
        inc.vector_sum = inc.vector_sum - vector
        inc.centroid = _unit(inc.vector_sum)
        inc.count -= 1
        return inc

    def relocate(self, incident_id: str, lat: float | None, lng: float | None, located_count: int) -> None:
        """Reset an incident's location (after a split recomputed it). O(1)."""
        inc = self._incidents[incident_id]
        if inc.cell is not None:
            self._cells[inc.cell].discard(incident_id)
        inc.lat = inc.lng = None
        inc.cell = None
        inc.located_count = 0
        if lat is not None and lng is not None and located_count:
            self._set_location(inc, lat, lng, weight=located_count)
        else:
            self._recent_unlocated[inc.department][incident_id] = None

    def drop(self, incident_id: str) -> None:
        """Remove an incident from every structure (heap entries go stale). O(1) amortised."""
        inc = self._incidents.pop(incident_id, None)
        if inc is None:
            return
        if inc.cell is not None:
            self._cells[inc.cell].discard(incident_id)
        self._recent[inc.department].pop(incident_id, None)
        self._recent_unlocated[inc.department].pop(incident_id, None)

    def expire(self) -> int:
        """Drop incidents idle longer than the window. O(log n) per expired heap entry."""
        cutoff = self._clock() - self._window_s
        dropped = 0
        while self._heap and self._heap[0][0] < cutoff:
            updated, incident_id = heapq.heappop(self._heap)
            inc = self._incidents.get(incident_id)
            if inc is not None and inc.last_updated == updated:
                self.drop(incident_id)
                dropped += 1
        return dropped

    def _set_location(self, inc: IndexedIncident, lat: float, lng: float, weight: int) -> None:
        total = inc.located_count + weight
        if inc.lat is None or inc.lng is None:
            inc.lat, inc.lng = lat, lng
        else:
            inc.lat += (lat - inc.lat) * weight / total
            inc.lng += (lng - inc.lng) * weight / total
        inc.located_count = total
        cell = self.cell_of(inc.lat, inc.lng)
        if cell != inc.cell:
            if inc.cell is not None:
                self._cells[inc.cell].discard(inc.id)
            self._cells[cell].add(inc.id)
            inc.cell = cell
        self._recent_unlocated[inc.department].pop(inc.id, None)

    def _touch(self, inc: IndexedIncident, now: float) -> None:
        inc.last_updated = now
        heapq.heappush(self._heap, (now, inc.id))
        recent = self._recent[inc.department]
        recent[inc.id] = None
        recent.move_to_end(inc.id)
        if inc.lat is None:
            unlocated = self._recent_unlocated[inc.department]
            unlocated[inc.id] = None
            unlocated.move_to_end(inc.id)
