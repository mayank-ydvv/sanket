"""SQLite storage via aiosqlite (WAL mode). The schema uses only Postgres-portable types."""

import json
import sqlite3
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Self

import aiosqlite

from app.models import Decision, DecisionResult, Report

SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    department TEXT NOT NULL,
    severity INTEGER NOT NULL,
    status TEXT NOT NULL,
    lat REAL,
    lng REAL,
    location_text TEXT,
    location_confirmed INTEGER NOT NULL DEFAULT 0,
    report_count INTEGER NOT NULL DEFAULT 0,
    first_seen REAL NOT NULL,
    last_updated REAL NOT NULL,
    linked_hazards TEXT,
    briefing TEXT,
    centroid BLOB
);
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,
    caller_hash TEXT,
    raw_text TEXT NOT NULL,
    language TEXT,
    english_gloss TEXT,
    received_at REAL NOT NULL,
    decision_json TEXT,
    confidence REAL,
    incident_id TEXT REFERENCES incidents(id),
    flags TEXT,
    source TEXT
);
CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES incidents(id),
    department TEXT NOT NULL,
    channel TEXT NOT NULL,
    sent_at REAL NOT NULL,
    acknowledged_at REAL,
    escalated_to TEXT,
    triggered_by TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    entity TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    before TEXT,
    after TEXT,
    at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS geocode_cache (
    query TEXT PRIMARY KEY,
    lat REAL,
    lng REAL,
    at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reports_incident ON reports(incident_id);
CREATE INDEX IF NOT EXISTS idx_reports_received ON reports(received_at);
CREATE INDEX IF NOT EXISTS idx_incidents_status_updated ON incidents(status, last_updated);
CREATE INDEX IF NOT EXISTS idx_alerts_incident ON alerts(incident_id);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity, entity_id);
"""

_REPORT_COLUMNS = (
    "id, channel, caller_hash, raw_text, language, english_gloss, received_at, "
    "decision_json, confidence, incident_id, flags, source"
)


def _row_to_report(row: sqlite3.Row) -> Report:
    decision = row["decision_json"]
    return Report(
        id=row["id"],
        channel=row["channel"],
        caller_hash=row["caller_hash"],
        raw_text=row["raw_text"],
        language=row["language"],
        english_gloss=row["english_gloss"],
        received_at=row["received_at"],
        decision=Decision.model_validate_json(decision) if decision else None,
        confidence=row["confidence"],
        incident_id=row["incident_id"],
        flags=json.loads(row["flags"]) if row["flags"] else [],
        source=row["source"],
    )


class Database:
    """Thin async wrapper over one aiosqlite connection (SQLite serialises writes anyway)."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    @classmethod
    async def open(cls, path: Path) -> Self:
        """Open the DB, enable WAL and run the idempotent migration."""
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(path)
        conn.row_factory = sqlite3.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.executescript(SCHEMA)
        await conn.commit()
        return cls(conn)

    async def close(self) -> None:
        await self._conn.close()

    async def insert_report(self, report: Report) -> None:
        """Insert a freshly received report (no decision yet). O(log n) index insert."""
        await self._conn.execute(
            "INSERT INTO reports (id, channel, caller_hash, raw_text, language, received_at, flags) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                report.id,
                report.channel,
                report.caller_hash,
                report.raw_text,
                report.language,
                report.received_at,
                json.dumps(report.flags),
            ),
        )
        await self._conn.commit()

    async def save_decisions(self, items: Sequence[tuple[str, DecisionResult]]) -> None:
        """Store a batch of decisions and their audit rows in one transaction. O(b log n)."""
        now = time.time()
        await self._conn.executemany(
            "UPDATE reports SET decision_json = ?, confidence = ?, source = ?, flags = ? WHERE id = ?",
            [
                (
                    result.decision.model_dump_json(),
                    result.confidence,
                    result.source,
                    json.dumps(result.rules_fired),
                    report_id,
                )
                for report_id, result in items
            ],
        )
        await self._conn.executemany(
            "INSERT INTO audit_log (entity, entity_id, action, actor, before, after, at) "
            "VALUES ('report', ?, 'decided', ?, NULL, ?, ?)",
            [
                (
                    report_id,
                    result.model,
                    result.model_dump_json(include={"decision", "source", "confidence", "prompt_version", "rules_fired"}),
                    now,
                )
                for report_id, result in items
            ],
        )
        await self._conn.commit()

    async def audit_for(self, entity: str, entity_id: str) -> list[dict[str, object]]:
        """Audit trail of one entity, oldest first. O(log n + k) via idx_audit_entity."""
        async with self._conn.execute(
            "SELECT action, actor, before, after, at FROM audit_log WHERE entity = ? AND entity_id = ? ORDER BY id",
            (entity, entity_id),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def recent_reports(self, limit: int) -> list[Report]:
        """Newest ``limit`` reports. O(log n + limit) via the received_at index."""
        async with self._conn.execute(
            f"SELECT {_REPORT_COLUMNS} FROM reports ORDER BY received_at DESC LIMIT ?", (limit,)
        ) as cursor:
            return [_row_to_report(row) for row in await cursor.fetchall()]

    async def table_names(self) -> list[str]:
        async with self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ) as cursor:
            return [row["name"] for row in await cursor.fetchall()]
