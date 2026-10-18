"""Phase 5: throttled broadcasts, escalation, progressive LLM revision, dispatcher actions."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.alerts.senders import MockSender
from app.alerts.service import AlertService
from app.cluster.embed import HashingEmbedder
from app.cluster.service import IncidentService
from app.config import Settings
from app.db import Database
from app.main import create_app
from app.models import Contact
from app.ws import Broadcaster
from tests.conftest import receive_event
from tests.test_incidents import make_index, placed
from tests.test_llm import FakeProvider, make_decider, valid_json


class RecordingHub:
    def __init__(self) -> None:
        self.messages: list[tuple[str, Any]] = []

    async def broadcast(self, event: str, data: Any) -> None:
        self.messages.append((event, data))


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    database = await Database.open(tmp_path / "live.db")
    yield database  # type: ignore[misc]
    await database.close()


# -- broadcaster -----------------------------------------------------------------


async def test_burst_coalesces_into_one_message_per_flush() -> None:
    hub = RecordingHub()
    b = Broadcaster(hub)  # type: ignore[arg-type]
    for i in range(1000):
        b.publish("incident.updated", {"id": f"i{i % 10}", "report_count": i})
    assert await b.flush() == 10
    (event, events), = hub.messages
    assert event == "batch" and len(events) == 10
    assert {e["data"]["report_count"] for e in events} == set(range(990, 1000))


async def test_updates_send_only_changed_fields() -> None:
    hub = RecordingHub()
    b = Broadcaster(hub)  # type: ignore[arg-type]
    b.publish("incident.created", {"id": "i1", "severity": 3, "title": "Fire · Sector 18"})
    await b.flush()
    b.publish("incident.updated", {"id": "i1", "severity": 4, "title": "Fire · Sector 18"})
    await b.flush()
    assert hub.messages[1][1] == [{"type": "incident.updated", "data": {"id": "i1", "severity": 4}}]
    b.publish("incident.updated", {"id": "i1", "severity": 4, "title": "Fire · Sector 18"})
    assert await b.flush() == 0 and len(hub.messages) == 2  # nothing changed, nothing sent


async def test_created_then_updated_in_one_window_stays_created() -> None:
    hub = RecordingHub()
    b = Broadcaster(hub)  # type: ignore[arg-type]
    b.publish("incident.created", {"id": "i1", "severity": 3})
    b.publish("incident.updated", {"id": "i1", "severity": 5})
    await b.flush()
    assert hub.messages[0][1] == [{"type": "incident.created", "data": {"id": "i1", "severity": 5}}]


async def test_flush_rate_is_at_most_ten_per_second() -> None:
    hub = RecordingHub()
    b = Broadcaster(hub, interval_s=0.1)  # type: ignore[arg-type]
    runner = asyncio.create_task(b.run())
    for i in range(300):
        b.publish("report.created", {"id": f"r{i}"})
        await asyncio.sleep(0.002)  # a 600 ms surge
    await asyncio.sleep(0.15)
    runner.cancel()
    assert sum(len(events) for _, events in hub.messages) == 300
    assert len(hub.messages) <= 8


# -- escalation ------------------------------------------------------------------


async def alert_setup(db: Database, clock: Clock) -> tuple[AlertService, MockSender, str, IncidentService]:
    incidents = IncidentService(db, make_index(), clock=clock)
    changes = await incidents.assign(await placed(db, HashingEmbedder(), ["fire at Sector 18 metro"]))
    sender = MockSender()
    ladder = {"fire": [Contact(name="Station"), Contact(name="Supervisor")]}
    alerts = AlertService(db, incidents, Broadcaster(RecordingHub()), sender, ladder, 90, clock=clock)  # type: ignore[arg-type]
    return alerts, sender, changes.created[0].id, incidents


async def test_unacknowledged_alert_escalates_at_90_seconds(db: Database) -> None:
    clock = Clock()
    alerts, sender, incident_id, incidents = await alert_setup(db, clock)
    first = await alerts.dispatch(incident_id, "auto")
    assert first is not None and first.contact == "Station"
    assert await alerts.dispatch(incident_id, "auto") is None  # no duplicate while live
    assert (await incidents.current(incident_id)).status == "dispatched"
    clock.now += 89
    assert await alerts.tick() == []
    clock.now += 2
    (second,) = await alerts.tick()
    assert second.contact == "Supervisor" and second.level == 1 and second.triggered_by == "escalation"
    assert [c.name for c, _ in sender.sent] == ["Station", "Supervisor"]
    stored = await db.alerts_for(incident_id)
    assert stored[0].escalated_to == "Supervisor"
    clock.now += 91
    assert await alerts.tick() == []  # ladder exhausted: no third contact
    assert (await db.alerts_for(incident_id))[1].escalated_to == "exhausted"


async def test_acknowledged_alert_never_escalates(db: Database) -> None:
    clock = Clock()
    alerts, sender, incident_id, _ = await alert_setup(db, clock)
    await alerts.dispatch(incident_id, "dispatcher")
    clock.now += 30
    acked = await alerts.acknowledge(incident_id, "dispatcher")
    assert acked.acknowledged_at == clock.now
    clock.now += 500
    assert await alerts.tick() == [] and len(sender.sent) == 1
    with pytest.raises(LookupError):
        await alerts.acknowledge(incident_id, "dispatcher")


async def test_escalation_timers_survive_restart(db: Database) -> None:
    clock = Clock()
    alerts, sender, incident_id, incidents = await alert_setup(db, clock)
    await alerts.dispatch(incident_id, "auto")
    restarted = AlertService(db, incidents, Broadcaster(RecordingHub()), sender, {"fire": [Contact(name="Station"), Contact(name="Supervisor")]}, 90, clock=clock)  # type: ignore[arg-type]
    assert await restarted.restore() == 1
    clock.now += 91
    assert len(await restarted.tick()) == 1


# -- progressive LLM revision + dispatcher endpoints --------------------------------


def test_local_decision_first_then_llm_revision_and_auto_dispatch(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = FakeProvider("fake", valid_json)
    answer = provider.complete

    async def slow_complete(system: str, user: str, max_output_tokens: int) -> Any:
        await asyncio.sleep(0.3)  # a real LLM call: the local decision is broadcast first
        return await answer(system, user, max_output_tokens)

    provider.complete = slow_complete  # type: ignore[method-assign]
    monkeypatch.setattr(main_module, "build_llm_decider", lambda cfg, http, limiters: make_decider(provider))
    with TestClient(create_app(settings)) as client, client.websocket_connect("/ws") as ws:
        report_id = client.post("/reports", json={"text": "Sector 18 metro pe kuch ho gaya, jaldi aao"}).json()["id"]
        first = receive_event(ws, "report.created")["data"]
        assert first["id"] == report_id and first["refining"] and first["source"] == "local"
        revised = receive_event(ws, "report.updated")["data"]
        assert revised["id"] == report_id and revised["source"] == "llm" and not revised["refining"]
        assert "incident_id" not in revised  # diff: only changed fields are sent
        assert revised["decision"]["department"] == "fire"
        alert = receive_event(ws, "alert.sent")["data"]
        assert alert["triggered_by"] == "auto" and alert["contact"] == "Fire station · Sector 6"
        incident = client.get(f"/incidents/{first['incident_id']}").json()
        assert incident["incident"]["department"] == "fire" and incident["incident"]["status"] == "dispatched"
        assert [a["contact"] for a in incident["alerts"]] == ["Fire station · Sector 6"]
    assert provider.calls == 1


def test_confirm_ack_override_endpoints(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client, client.websocket_connect("/ws") as ws:
        client.post("/reports", json={"text": "Sector 18 metro pe building mein aag"})
        incident_id = receive_event(ws, "report.created")["data"]["incident_id"]
        alert = client.post(f"/incidents/{incident_id}/confirm").json()
        assert alert["triggered_by"] == "dispatcher" and alert["level"] == 0
        assert client.post(f"/incidents/{incident_id}/confirm").json() is None
        assert [a["id"] for a in client.get("/alerts").json()] == [alert["id"]]
        assert client.post(f"/incidents/{incident_id}/ack").json()["acknowledged_at"] is not None
        assert client.post(f"/incidents/{incident_id}/ack").status_code == 404
        overridden = client.post(f"/incidents/{incident_id}/override", json={"department": "fire", "severity": 5, "note": "confirmed by caller"})
        assert overridden.status_code == 200
        body = overridden.json()
        assert body["department"] == "fire" and body["severity"] == 5 and body["overrides"] == {"department": "fire", "severity": 5}
        audit = client.get(f"/incidents/{incident_id}").json()["audit"]
        override = next(a for a in audit if a["action"] == "override")
        assert '"severity": 5' in override["after"] and "confirmed by caller" in override["after"]
        assert client.post("/incidents/missing/confirm").status_code == 404
        assert client.post(f"/incidents/{incident_id}/override", json={"severity": 9}).status_code == 422


async def test_revision_that_changes_department_moves_report_to_right_incident(db: Database) -> None:
    import numpy as np

    from app.cluster.service import Revision
    from app.models import DecisionResult
    from tests.test_incidents import SECTOR_18, decision

    def unit(seed: int) -> np.ndarray:
        v = np.random.default_rng(seed).normal(size=64).astype(np.float32)
        return v / np.linalg.norm(v)

    incidents = IncidentService(db, make_index())
    fire_items = await placed(db, HashingEmbedder(), ["fire at Sector 18 metro"], department="fire")
    fire_items = [item.__class__(**{**item.__dict__, "vector": unit(1)}) for item in fire_items]
    fire = (await incidents.assign(fire_items)).created[0]
    wrong = await placed(db, HashingEmbedder(), ["aag lagi Sector 18 metro"], department="police")
    wrong = [item.__class__(**{**item.__dict__, "vector": unit(2)}) for item in wrong]
    police = (await incidents.assign(wrong)).created[0]
    assert police.id != fire.id and police.department == "police"

    revised = DecisionResult(decision=decision("fire", 4), source="llm", confidence=0.95, model="fake/llm")
    changes = await incidents.revise([Revision(wrong[0].report.id, revised, unit(1), "Sector 18 metro", SECTOR_18)])
    by_id = {i.id: i for i in changes.updated}
    assert by_id[fire.id].report_count == 2
    assert by_id[police.id].status == "merged"
    assert (await db.report(wrong[0].report.id))[0].incident_id == fire.id  # type: ignore[index]
    assert "report_moved" in [a.action for a in await db.audit_for("incident", fire.id)]


async def test_lane_needs_majority_flags_for_review_but_any_silent_sos(db: Database) -> None:
    from app.cluster.service import IncidentMeta
    from app.models import Report

    meta = IncidentMeta(first_seen=0)
    confident = dict(is_emergency=True, emergency_prob=0.95, department="fire", department_conf=0.95, severity=4, alert_now=True)
    from app.models import Decision

    for review in (False, False, True):
        meta.add(Report(id="r", channel="sms", caller_hash=None, raw_text="x", received_at=0, decision=Decision(**confident, needs_human_review=review)), False)
    assert meta.lane == "auto"
    meta.add(Report(id="s", channel="sms", caller_hash=None, raw_text="1111", received_at=0, decision=Decision(**confident, silent_sos=True)), False)
    assert meta.lane == "review"


async def test_escalation_follows_the_alerts_own_ladder_after_department_change(db: Database) -> None:
    from app.models import OverrideRequest

    clock = Clock()
    incidents = IncidentService(db, make_index(), clock=clock)
    changes = await incidents.assign(await placed(db, HashingEmbedder(), ["fire at Sector 18 metro"]))
    incident_id = changes.created[0].id
    ladders = {"fire": [Contact(name="Station"), Contact(name="Supervisor")], "none": [Contact(name="Control room")]}
    alerts = AlertService(db, incidents, Broadcaster(RecordingHub()), MockSender(), ladders, 90, clock=clock)  # type: ignore[arg-type]
    await alerts.dispatch(incident_id, "auto")
    await incidents.override(incident_id, OverrideRequest(department="none"), actor="dispatcher")  # 1-rung ladder now
    clock.now += 91
    (second,) = await alerts.tick()
    assert second.contact == "Supervisor" and second.department == "fire"


async def test_department_change_after_dispatch_alerts_the_new_department(db: Database) -> None:
    from app.models import OverrideRequest

    clock = Clock()
    incidents = IncidentService(db, make_index(), clock=clock)
    changes = await incidents.assign(await placed(db, HashingEmbedder(), ["fire at Sector 18 metro"], department="disaster"))
    incident_id = changes.created[0].id
    sender = MockSender()
    ladders = {"disaster": [Contact(name="SDRF"), Contact(name="DM")], "fire": [Contact(name="Fire station"), Contact(name="CFO")]}
    alerts = AlertService(db, incidents, Broadcaster(RecordingHub()), sender, ladders, 90, clock=clock)  # type: ignore[arg-type]
    await alerts.dispatch(incident_id, "auto")
    unchanged = await incidents.current(incident_id)
    assert await alerts.reroute_if_department_changed(unchanged) is None
    corrected = await incidents.override(incident_id, OverrideRequest(department="fire"), actor="dispatcher")
    rerouted = await alerts.reroute_if_department_changed(corrected)
    assert rerouted is not None and rerouted.contact == "Fire station" and rerouted.triggered_by == "department_changed"
    first = (await db.alerts_for(incident_id))[0]
    assert first.contact == "SDRF" and first.escalated_to == "rerouted:fire"
    clock.now += 91
    (escalated,) = await alerts.tick()  # only the new department's alert keeps escalating
    assert escalated.contact == "CFO"
    assert [c.name for c, _ in sender.sent] == ["SDRF", "Fire station", "CFO"]
