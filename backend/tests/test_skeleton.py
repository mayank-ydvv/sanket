import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.db import Database
from app.models import Decision
from app.privacy import hash_caller
from tests.conftest import TEST_SALT

EXPECTED_TABLES = {"reports", "incidents", "alerts", "audit_log", "geocode_cache"}


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


async def test_migration_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "m.db"
    for _ in range(2):
        db = await Database.open(path)
        assert EXPECTED_TABLES <= set(await db.table_names())
        await db.close()
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_reports_incident", "idx_incidents_status_updated", "idx_alerts_incident"} <= indexes


def test_report_is_broadcast_over_websocket(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        response = client.post(
            "/reports",
            json={"text": "aag lagi hai sector 18", "channel": "sms", "caller": "+91 99999 99999"},
        )
        assert response.status_code == 202
        event = ws.receive_json()
    assert event["type"] == "report.created"
    data = event["data"]
    assert data["id"] == response.json()["id"]
    assert data["raw_text"] == "aag lagi hai sector 18"
    assert data["decision"]["needs_human_review"] is True
    assert data["caller_hash"] == hash_caller("+919999999999", TEST_SALT)


def test_raw_caller_number_is_never_stored(client: TestClient, settings: Settings) -> None:
    with client.websocket_connect("/ws") as ws:
        client.post("/reports", json={"text": "help", "caller": "+919876543210"})
        ws.receive_json()
    dump = "\n".join(sqlite3.connect(settings.db_path).iterdump())
    assert "9876543210" not in dump


def test_list_reports_returns_decided_report(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        client.post("/reports", json={"text": "accident on expressway"})
        ws.receive_json()
    reports = client.get("/reports").json()
    assert [r["raw_text"] for r in reports] == ["accident on expressway"]
    assert reports[0]["source"] == "local"


def test_invalid_report_rejected(client: TestClient) -> None:
    assert client.post("/reports", json={"text": "x", "channel": "pigeon"}).status_code == 422
    assert client.post("/reports", json={"text": "x", "extra": 1}).status_code == 422


def test_decision_schema_is_strict() -> None:
    valid = {
        "is_emergency": True,
        "emergency_prob": 0.94,
        "department": "fire",
        "department_conf": 0.88,
        "severity": 4,
        "alert_now": True,
    }
    assert Decision.model_validate(valid).severity == 4
    for bad in ({"severity": 6}, {"department": "army"}, {"emergency_prob": "0.9"}, {"foo": 1}):
        with pytest.raises(ValidationError):
            Decision.model_validate(valid | bad)


def test_decision_is_audited(client: TestClient, settings: Settings) -> None:
    with client.websocket_connect("/ws") as ws:
        report_id = client.post("/reports", json={"text": "1111 1111 1111"}).json()["id"]
        data = ws.receive_json()["data"]
    assert data["decision"]["silent_sos"] and data["lane"] == "review"
    assert data["flags"] == ["silent_sos:tap_code"] and data["source"] == "rules"
    row = sqlite3.connect(settings.db_path).execute(
        "SELECT action, actor, after FROM audit_log WHERE entity = 'report' AND entity_id = ?", (report_id,)
    ).fetchone()
    assert row[0] == "decided" and row[1] == "untriaged" and "silent_sos" in row[2]
