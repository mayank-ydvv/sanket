import random
import time
from collections.abc import Sequence
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.cluster.embed import Embedder, HashingEmbedder, SentenceEmbedder, embedding_text
from app.cluster.geocode import GeoPoint
from app.cluster.index import IncidentIndex
from app.cluster.location import gazetteer_lookup
from app.cluster.service import IncidentService, Placed
from app.config import Settings
from app.db import Database
from app.decision.rules import detect_hazards
from app.main import create_app
from app.models import Decision, DecisionResult, Report
from tests.conftest import receive_event
from tests.surge import seeded_events, surge

MARINA = GeoPoint(13.0500, 80.2824, "gazetteer")


def make_index() -> IncidentIndex:
    return IncidentIndex(13.04, 1.0, 1800, 0.70, 0.15, 50)


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    database = await Database.open(tmp_path / "incidents.db")
    yield database  # type: ignore[misc]
    await database.close()


def decision(department: str = "fire", severity: int = 3, text: str = "") -> Decision:
    return Decision(
        is_emergency=True, emergency_prob=0.95, department=department, department_conf=0.95,  # type: ignore[arg-type]
        severity=severity, alert_now=True, hazards=detect_hazards(text),
    )


async def placed(
    db: Database,
    embedder: Embedder,
    texts: Sequence[str],
    *,
    department: str = "fire",
    severity: int = 3,
    point: GeoPoint | None = MARINA,
    location: str | None = "Marina beach",
) -> list[Placed]:
    reports = [
        Report(id=f"r_{time.perf_counter_ns()}_{i}", channel="sms", caller_hash=None, raw_text=t, received_at=time.time())
        for i, t in enumerate(texts)
    ]
    async with db.transaction():
        for report in reports:
            await db.insert_report(report)
    decisions = [decision(department, severity, t) for t in texts]
    vectors = embedder.encode([embedding_text(t, d) for t, d in zip(texts, decisions, strict=True)])
    return [
        Placed(r, DecisionResult(decision=d, source="local", confidence=0.95, model="test"), vectors[i], location, point)
        for i, (r, d) in enumerate(zip(reports, decisions, strict=True))
    ]


async def test_duplicates_become_one_incident_with_severity_rule(db: Database) -> None:
    service = IncidentService(db, make_index())
    embedder = HashingEmbedder()
    out = await service.assign(await placed(db, embedder, ["building on fire at Marina beach"] * 11))
    open_incidents = await db.incidents("open", 10)
    assert len(open_incidents) == 1 and open_incidents[0].report_count == 11
    assert open_incidents[0].severity == 4  # max 3, +1 past 10 reports
    assert open_incidents[0].title == "Fire · Marina beach" and open_incidents[0].location_confirmed
    assert {r.incident_id for r in out.reports} == {open_incidents[0].id}


async def test_trapped_people_escalate_severity(db: Database) -> None:
    service = IncidentService(db, make_index())
    out = await service.assign(await placed(db, HashingEmbedder(), ["fire at Marina beach, 2 people trapped"]))
    assert out.created[0].severity == 4


async def test_split_moves_one_report_out(db: Database) -> None:
    service = IncidentService(db, make_index())
    items = await placed(db, HashingEmbedder(), ["fire in building at Marina beach"] * 3)
    await service.assign(items)
    incident_id = (await db.incidents("open", 10))[0].id
    original, new = await service.split(incident_id, items[0].report.id)
    assert original.report_count == 2 and new.report_count == 1
    assert (await db.report(items[0].report.id))[0].incident_id == new.id  # type: ignore[index]
    assert [a.action for a in await db.audit_for("incident", incident_id)][-1] == "split"
    with pytest.raises(LookupError):
        await service.split(incident_id, items[0].report.id)


async def test_restore_rebuilds_the_index(db: Database) -> None:
    embedder = HashingEmbedder()
    await IncidentService(db, make_index()).assign(await placed(db, embedder, ["fire at Marina beach"] * 2))
    restarted = IncidentService(db, make_index())
    assert await restarted.restore() == 1
    out = await restarted.assign(await placed(db, embedder, ["fire at Marina beach"]))
    assert not out.created and out.updated[0].report_count == 3


async def test_different_departments_at_one_place_stay_apart(db: Database) -> None:
    service = IncidentService(db, make_index())
    embedder = HashingEmbedder()
    await service.assign(await placed(db, embedder, ["building on fire at Marina beach"]))
    await service.assign(await placed(db, embedder, ["two men fighting with knives at Marina beach"], department="police"))
    assert len(await db.incidents("open", 10)) == 2


def test_incident_api_list_detail_split(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client, client.websocket_connect("/ws") as ws:
        ids = [client.post("/reports", json={"text": "Marina beach pe building mein aag lagi hai"}).json()["id"] for _ in range(2)]
        for _ in ids:
            receive_event(ws, "report.created")
        incidents = client.get("/incidents").json()
        assert len(incidents) == 1 and incidents[0]["report_count"] == 2
        detail = client.get(f"/incidents/{incidents[0]['id']}").json()
        assert {r["id"] for r in detail["reports"]} == set(ids)
        assert detail["audit"][0]["action"] == "created"
        split = client.post(f"/incidents/{incidents[0]['id']}/split", json={"report_id": ids[0]})
        assert split.status_code == 200 and split.json()["new"]["report_count"] == 1
        assert client.post(f"/incidents/{incidents[0]['id']}/split", json={"report_id": "nope"}).status_code == 404
        assert client.get("/incidents/missing").status_code == 404


@pytest.fixture(scope="module")
def sentence_embedder() -> SentenceEmbedder:
    return SentenceEmbedder(Settings(_env_file=None, caller_salt="x" * 16).embedding_model)  # type: ignore[call-arg]


@pytest.mark.parametrize("seed", [1, 7, 42])
async def test_500_reports_about_12_events_give_12_plus_minus_2_incidents(
    db: Database, sentence_embedder: SentenceEmbedder, seed: int
) -> None:
    """Acceptance test: a multilingual surge collapses to about one incident per event."""
    rng = random.Random(seed)
    reports = surge(seeded_events(12, rng), 500, rng)
    service = IncidentService(db, make_index())
    start = time.perf_counter()
    for i in range(0, len(reports), 25):
        batch = reports[i : i + 25]
        items: list[Placed] = []
        for r in batch:
            place = gazetteer_lookup(r.location) if r.location else None
            point = GeoPoint(place.lat, place.lng, "gazetteer") if place else None
            items += await placed(db, sentence_embedder, [r.text], department=r.department, point=point, location=r.location)
        await service.assign(items)
    elapsed = time.perf_counter() - start
    open_incidents = await db.incidents("open", 100)
    print(f"\nseed {seed}: 500 reports -> {len(open_incidents)} incidents in {elapsed:.1f}s")
    assert 10 <= len(open_incidents) <= 14
    assert sum(i.report_count for i in open_incidents) == 500


async def test_silent_sos_reports_never_merge(db: Database) -> None:
    service = IncidentService(db, make_index())
    embedder = HashingEmbedder()
    robbery = await placed(db, embedder, ["robbery at a jewellery shop"], department="police", point=None, location=None)
    await service.assign(robbery)
    silent: list[Placed] = []
    for text in ("1111 1111 1111", "1111 1111 1111"):
        item = (await placed(db, embedder, [text], department="police", point=None, location=None))[0]
        sos = item.result.decision.model_copy(update={"silent_sos": True, "needs_human_review": True})
        silent.append(Placed(item.report, item.result.model_copy(update={"decision": sos}), item.vector, None, None))
    out = await service.assign(silent)
    assert len(out.created) == 2  # two callers, two incidents, neither joins the robbery
    later = await placed(db, embedder, ["1111 1111 1111 robbery"], department="police", point=None, location=None)
    joined = await service.assign(later)
    assert not any(i.silent_sos for i in joined.updated)
    assert len([i for i in await db.incidents("open", 10) if i.silent_sos]) == 2
