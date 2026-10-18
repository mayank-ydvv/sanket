import math
import random
import time

import numpy as np

from app.cluster.index import IncidentIndex, haversine_km

DIM = 32
LAT, LNG = 13.0500, 80.2824  # Marina beach


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def unit(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).normal(size=DIM).astype(np.float32)
    return v / np.linalg.norm(v)


def make_index(clock: Clock | None = None) -> IncidentIndex:
    return IncidentIndex(13.04, 1.0, 1800, 0.7, 0.15, 50, clock=clock or Clock())


def km_north(lat: float, km: float) -> float:
    return lat + km / 111.32


def test_duplicates_join_the_same_incident() -> None:
    idx = make_index()
    v = unit(1)
    idx.add("a", v, "fire", LAT, LNG)
    match = idx.best_match(v, "fire", LAT + 0.001, LNG)
    assert match is not None and match.incident_id == "a"


def test_same_text_two_km_apart_stays_separate() -> None:
    idx = make_index()
    v = unit(1)
    idx.add("a", v, "fire", LAT, LNG)
    far = km_north(LAT, 2.0)
    assert haversine_km(LAT, LNG, far, LNG) > 1.9
    assert idx.best_match(v, "fire", far, LNG) is None


def test_neighbouring_cell_within_radius_still_matches() -> None:
    idx = make_index()
    v = unit(3)
    idx.add("a", v, "fire", LAT, LNG)
    near = km_north(LAT, 0.9)  # likely a different grid cell, still inside 1 km
    match = idx.best_match(v, "fire", near, LNG)
    assert match is not None and match.incident_id == "a"


def test_unlocated_report_matches_same_department_by_text() -> None:
    idx = make_index()
    idx.add("fire", unit(1), "fire", LAT, LNG)
    idx.add("police", unit(1), "police", LAT, LNG)
    match = idx.best_match(unit(1), "fire", None, None)
    assert match is not None and match.incident_id == "fire"
    assert idx.best_match(unit(2), "medical", None, None) is None


def test_dissimilar_text_does_not_join() -> None:
    idx = make_index()
    idx.add("a", unit(1), "fire", LAT, LNG)
    assert idx.best_match(unit(99), "fire", LAT, LNG) is None


def test_idle_incidents_expire_from_index() -> None:
    clock = Clock()
    idx = make_index(clock)
    idx.add("old", unit(1), "fire", LAT, LNG)
    clock.now += 1000
    idx.add("new", unit(2), "fire", LAT, LNG)
    idx.join("old", unit(1), LAT, LNG)  # touched: stale heap entry left behind
    clock.now += 1500
    assert idx.expire() == 0  # both updated 1500 s ago (< 1800)
    clock.now += 400
    assert idx.expire() == 2 and len(idx) == 0
    assert idx.best_match(unit(1), "fire", LAT, LNG) is None


def test_join_updates_centroid_and_location() -> None:
    idx = make_index()
    idx.add("a", unit(1), "fire", LAT, LNG)
    inc = idx.join("a", unit(1), km_north(LAT, 0.2), LNG)
    assert inc.count == 2
    assert math.isclose(float(np.linalg.norm(inc.centroid)), 1.0, rel_tol=1e-5)
    assert inc.lat is not None and LAT < inc.lat < km_north(LAT, 0.2)


def test_twin_found_and_merged_after_location_arrives() -> None:
    idx = make_index()
    idx.add("located", unit(1), "fire", LAT, LNG)
    idx.add("unlocated", unit(1), "fire", None, None)
    twin = idx.find_twin("unlocated")
    assert twin is not None and twin.incident_id == "located"
    keep = idx.merge("located", "unlocated")
    assert keep.count == 2 and "unlocated" not in idx


def test_remove_report_and_relocate() -> None:
    idx = make_index()
    idx.add("a", unit(1), "fire", LAT, LNG)
    idx.join("a", unit(2), LAT, LNG)
    inc = idx.remove_report("a", unit(2))
    assert inc is not None and inc.count == 1
    assert float(inc.centroid @ unit(1)) > 0.99
    idx.relocate("a", None, None, 0)
    assert idx.get("a").lat is None  # type: ignore[union-attr]
    assert idx.best_match(unit(1), "fire", None, None) is not None


DENSITY_PER_KM2 = 0.5  # open incidents per km², a heavy city-wide surge


def _populate(n: int, rng: random.Random) -> tuple[IncidentIndex, float]:
    """n incidents at constant density: the covered square grows with n."""
    side_deg = math.sqrt(n / DENSITY_PER_KM2) / 111.32
    idx = make_index()
    for i in range(n):
        idx.add(f"i{i}", unit(i), rng.choice(("fire", "police", "medical")), 28.0 + rng.random() * side_deg, 77.0 + rng.random() * side_deg)
    return idx, side_deg


def _queries(side_deg: float, rng: random.Random, count: int = 400) -> list[tuple[np.ndarray, float, float]]:
    return [(unit(10**6 + i), 28.0 + rng.random() * side_deg, 77.0 + rng.random() * side_deg) for i in range(count)]


def _per_lookup_us(idx: IncidentIndex, queries: list[tuple[np.ndarray, float, float]]) -> float:
    start = time.perf_counter()
    for v, lat, lng in queries:
        idx.best_match(v, "fire", lat, lng)
    return (time.perf_counter() - start) * 1e6 / len(queries)


def test_lookup_cost_is_flat_in_total_incidents_at_constant_density() -> None:
    """Micro-benchmark: 100x more open incidents (same local density) costs about the same."""
    rng = random.Random(0)
    small, side_small = _populate(200, rng)
    large, side_large = _populate(20_000, rng)
    t_small = min(_per_lookup_us(small, _queries(side_small, rng)) for _ in range(3))
    t_large = min(_per_lookup_us(large, _queries(side_large, rng)) for _ in range(3))
    print(f"\nlookup: {t_small:.1f} µs @ 200 incidents, {t_large:.1f} µs @ 20,000 incidents")
    assert t_large < t_small * 3  # a linear scan would be ~100x


def test_index_beats_brute_force_scan() -> None:
    rng = random.Random(1)
    idx, side = _populate(20_000, rng)
    queries = _queries(side, rng, 200)
    centroids = np.stack([idx.get(f"i{i}").centroid for i in range(20_000)])  # type: ignore[union-attr]
    start = time.perf_counter()
    for v, _, _ in queries:
        int(np.argmax(centroids @ v))
    brute_us = (time.perf_counter() - start) * 1e6 / len(queries)
    indexed_us = min(_per_lookup_us(idx, queries) for _ in range(3))
    print(f"\nbrute force {brute_us:.0f} µs vs index {indexed_us:.1f} µs per lookup @ 20,000")
    assert indexed_us * 5 < brute_us
