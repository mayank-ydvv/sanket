"""SQLite storage via aiosqlite (WAL mode). The schema uses only Postgres-portable types."""

import asyncio
import contextlib
import json
import sqlite3
import time
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any, Self

import aiosqlite

from app.models import Alert, AuditEntry, Decision, DecisionResult, Incident, Report

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
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at REAL NOT NULL
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

# Columns added after the first schema; applied idempotently with ALTER TABLE.
ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("reports", "location_text", "TEXT"),
    ("reports", "lat", "REAL"),
    ("reports", "lng", "REAL"),
    ("reports", "embedding", "BLOB"),
    ("incidents", "summary_json", "TEXT"),
    ("alerts", "contact", "TEXT"),
    ("alerts", "level", "INTEGER"),
)
_SUMMARY_FIELDS = frozenset(
    {
        "lane", "confidence", "silent_sos", "prank_suspected", "needs_review", "overrides",
        "combined_risk", "risk_hazards", "merge_suggestions", "reasoned_at",
    }
)

_REPORT_COLUMNS = (
    "id, channel, caller_hash, raw_text, language, english_gloss, received_at, "
    "decision_json, confidence, incident_id, flags, source, location_text, lat, lng"
)
_INCIDENT_COLUMNS = (
    "id, title, department, severity, status, lat, lng, location_text, location_confirmed, "
    "report_count, first_seen, last_updated, linked_hazards, briefing, summary_json"
)
_ALERT_COLUMNS = (
    "id, incident_id, department, channel, contact, level, sent_at, acknowledged_at, "
    "escalated_to, triggered_by"
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
        location_text=row["location_text"],
        lat=row["lat"],
        lng=row["lng"],
    )


def _row_to_incident(row: sqlite3.Row) -> Incident:
    return Incident(
        id=row["id"],
        title=row["title"],
        department=row["department"],
        severity=row["severity"],
        status=row["status"],
        lat=row["lat"],
        lng=row["lng"],
        location_text=row["location_text"],
        location_confirmed=bool(row["location_confirmed"]),
        report_count=row["report_count"],
        first_seen=row["first_seen"],
        last_updated=row["last_updated"],
        linked_hazards=json.loads(row["linked_hazards"]) if row["linked_hazards"] else [],
        briefing=json.loads(row["briefing"]) if row["briefing"] else None,
        **(json.loads(row["summary_json"]) if row["summary_json"] else {}),
    )


def _row_to_alert(row: sqlite3.Row) -> Alert:
    return Alert(**{key: row[key] for key in row.keys()})


class Database:
    """Async wrapper over one aiosqlite connection.

    Write methods do not commit: call them inside ``async with db.transaction()``,
    which serialises writers with a lock and commits once at the end, so a batch
    of reports and incidents lands atomically.
    """

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._write_lock = asyncio.Lock()

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
        for table, column, kind in ADDED_COLUMNS:
            async with conn.execute(f"PRAGMA table_info({table})") as cursor:
                existing = {row["name"] for row in await cursor.fetchall()}
            if column not in existing:
                await conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
        await conn.commit()
        return cls(conn)

    async def close(self) -> None:
        await self._conn.close()

    @contextlib.asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        async with self._write_lock:
            try:
                yield
            except BaseException:
                await self._conn.rollback()
                raise
            await self._conn.commit()

    # -- writes (inside a transaction) -----------------------------------------

    async def insert_report(self, report: Report) -> None:
        """Insert a freshly received report (no decision yet). O(log n)."""
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

    async def save_glosses(self, items: Sequence[tuple[str, str]]) -> None:
        """Store English translations ("" = already English). O(b log n)."""
        await self._conn.executemany("UPDATE reports SET english_gloss = ? WHERE id = ?", [(g, i) for i, g in items])

    async def save_decisions(
        self, items: Sequence[tuple[str, DecisionResult]], action: str = "decided"
    ) -> None:
        """Store a batch of decisions plus one audit row each. O(b log n)."""
        now = time.time()
        await self._conn.executemany(
            "UPDATE reports SET decision_json = ?, confidence = ?, source = ?, flags = ?, "
            "english_gloss = COALESCE(?, english_gloss) WHERE id = ?",
            [
                (
                    result.decision.model_dump_json(),
                    result.confidence,
                    result.source,
                    json.dumps(result.rules_fired),
                    result.english_gloss,
                    report_id,
                )
                for report_id, result in items
            ],
        )
        await self.audit(
            [
                (
                    "report",
                    report_id,
                    action,
                    result.model,
                    None,
                    result.model_dump_json(
                        include={"decision", "source", "confidence", "prompt_version", "rules_fired"}
                    ),
                )
                for report_id, result in items
            ],
            at=now,
        )

    async def save_report_placement(
        self,
        rows: Sequence[tuple[str | None, str | None, float | None, float | None, bytes | None, str]],
    ) -> None:
        """(incident_id, location_text, lat, lng, embedding, report_id) per report. O(b log n)."""
        await self._conn.executemany(
            "UPDATE reports SET incident_id = ?, location_text = ?, lat = ?, lng = ?, embedding = ? "
            "WHERE id = ?",
            rows,
        )

    async def move_reports(self, from_incident: str, to_incident: str) -> None:
        await self._conn.execute(
            "UPDATE reports SET incident_id = ? WHERE incident_id = ?", (to_incident, from_incident)
        )

    async def set_report_incident(self, report_id: str, incident_id: str) -> None:
        await self._conn.execute("UPDATE reports SET incident_id = ? WHERE id = ?", (incident_id, report_id))

    async def upsert_incidents(self, rows: Sequence[tuple[Incident, bytes | None]]) -> None:
        """Insert or update incidents with their unit centroid. O(b log n)."""
        await self._conn.executemany(
            f"INSERT INTO incidents ({_INCIDENT_COLUMNS}, centroid) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET title = excluded.title, department = excluded.department, "
            "severity = excluded.severity, status = excluded.status, lat = excluded.lat, "
            "lng = excluded.lng, location_text = excluded.location_text, "
            "location_confirmed = excluded.location_confirmed, report_count = excluded.report_count, "
            "last_updated = excluded.last_updated, linked_hazards = excluded.linked_hazards, "
            "briefing = excluded.briefing, summary_json = excluded.summary_json, "
            "centroid = COALESCE(excluded.centroid, incidents.centroid)",
            [
                (
                    i.id,
                    i.title,
                    i.department,
                    i.severity,
                    i.status,
                    i.lat,
                    i.lng,
                    i.location_text,
                    int(i.location_confirmed),
                    i.report_count,
                    i.first_seen,
                    i.last_updated,
                    json.dumps(i.linked_hazards),
                    json.dumps(i.briefing) if i.briefing is not None else None,
                    i.model_dump_json(include=_SUMMARY_FIELDS),
                    centroid,
                )
                for i, centroid in rows
            ],
        )

    async def audit(
        self, rows: Sequence[tuple[str, str, str, str, str | None, str | None]], at: float | None = None
    ) -> None:
        """Append (entity, entity_id, action, actor, before, after) rows. O(b)."""
        when = time.time() if at is None else at
        await self._conn.executemany(
            "INSERT INTO audit_log (entity, entity_id, action, actor, before, after, at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(*row, when) for row in rows],
        )

    async def update_report_embedding(self, report_id: str, embedding: bytes) -> None:
        await self._conn.execute("UPDATE reports SET embedding = ? WHERE id = ?", (embedding, report_id))

    async def update_report_location(
        self, report_id: str, location_text: str | None, lat: float | None, lng: float | None
    ) -> None:
        await self._conn.execute(
            "UPDATE reports SET location_text = ?, lat = ?, lng = ? WHERE id = ?",
            (location_text, lat, lng, report_id),
        )

    async def insert_alert(self, alert: Alert) -> None:
        await self._conn.execute(
            f"INSERT INTO alerts ({_ALERT_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                alert.id, alert.incident_id, alert.department, alert.channel, alert.contact,
                alert.level, alert.sent_at, alert.acknowledged_at, alert.escalated_to, alert.triggered_by,
            ),
        )

    async def update_alert(self, alert_id: str, acknowledged_at: float | None, escalated_to: str | None) -> None:
        await self._conn.execute(
            "UPDATE alerts SET acknowledged_at = ?, escalated_to = ? WHERE id = ?",
            (acknowledged_at, escalated_to, alert_id),
        )

    async def set_incident_status(self, incident_id: str, status: str) -> None:
        await self._conn.execute("UPDATE incidents SET status = ? WHERE id = ?", (status, incident_id))

    async def create_user(self, user_id: str, name: str, email: str, password_hash: str) -> None:
        await self._conn.execute(
            "INSERT INTO users (id, name, email, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, name, email, password_hash, time.time()),
        )

    async def geocode_cache_put(self, query: str, lat: float | None, lng: float | None) -> None:
        await self._conn.execute(
            "INSERT OR REPLACE INTO geocode_cache (query, lat, lng, at) VALUES (?, ?, ?, ?)",
            (query, lat, lng, time.time()),
        )

    # -- reads ----------------------------------------------------------------

    async def _fetch(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        async with self._conn.execute(sql, params) as cursor:
            return list(await cursor.fetchall())

    async def recent_reports(self, limit: int) -> list[Report]:
        """Newest ``limit`` reports. O(log n + limit) via the received_at index."""
        rows = await self._fetch(
            f"SELECT {_REPORT_COLUMNS} FROM reports ORDER BY received_at DESC LIMIT ?", (limit,)
        )
        return [_row_to_report(row) for row in rows]

    async def report(self, report_id: str) -> tuple[Report, bytes | None] | None:
        rows = await self._fetch(f"SELECT {_REPORT_COLUMNS}, embedding FROM reports WHERE id = ?", (report_id,))
        return (_row_to_report(rows[0]), rows[0]["embedding"]) if rows else None

    async def incident_reports(self, incident_id: str) -> list[tuple[Report, bytes | None]]:
        """Reports of one incident with embeddings, oldest first. O(log n + r)."""
        rows = await self._fetch(
            f"SELECT {_REPORT_COLUMNS}, embedding FROM reports WHERE incident_id = ? ORDER BY received_at",
            (incident_id,),
        )
        return [(_row_to_report(row), row["embedding"]) for row in rows]

    async def incident(self, incident_id: str) -> Incident | None:
        rows = await self._fetch(f"SELECT {_INCIDENT_COLUMNS} FROM incidents WHERE id = ?", (incident_id,))
        return _row_to_incident(rows[0]) if rows else None

    async def incidents(self, status: str | None, limit: int) -> list[Incident]:
        """Ranked by severity, then longest waiting. O(log n + limit) on the status index."""
        where, params = ("WHERE status = ?", [status]) if status else ("", [])
        rows = await self._fetch(
            f"SELECT {_INCIDENT_COLUMNS} FROM incidents {where} "
            "ORDER BY severity DESC, first_seen ASC LIMIT ?",
            [*params, limit],
        )
        return [_row_to_incident(row) for row in rows]

    async def open_incidents_since(self, since: float) -> list[tuple[Incident, bytes | None]]:
        """Open incidents updated after ``since`` with centroids (index restore)."""
        rows = await self._fetch(
            f"SELECT {_INCIDENT_COLUMNS}, centroid FROM incidents "
            "WHERE status = 'open' AND last_updated >= ?",
            (since,),
        )
        return [(_row_to_incident(row), row["centroid"]) for row in rows]

    async def alerts_for(self, incident_id: str) -> list[Alert]:
        """Alerts of one incident, oldest first. O(log n + k) via idx_alerts_incident."""
        rows = await self._fetch(
            f"SELECT {_ALERT_COLUMNS} FROM alerts WHERE incident_id = ? ORDER BY sent_at", (incident_id,)
        )
        return [_row_to_alert(row) for row in rows]

    async def recent_alerts(self, limit: int) -> list[Alert]:
        """Newest alerts first. O(n log n) sort; alert volume is small (one per dispatch)."""
        rows = await self._fetch(f"SELECT {_ALERT_COLUMNS} FROM alerts ORDER BY sent_at DESC LIMIT ?", (limit,))
        return [_row_to_alert(row) for row in rows]

    async def unacknowledged_alerts(self) -> list[Alert]:
        """Live alerts still waiting for an ack (escalation restore). O(a)."""
        rows = await self._fetch(
            f"SELECT {_ALERT_COLUMNS} FROM alerts WHERE acknowledged_at IS NULL AND escalated_to IS NULL"
        )
        return [_row_to_alert(row) for row in rows]

    async def audit_for(self, entity: str, entity_id: str) -> list[AuditEntry]:
        """Audit trail of one entity, oldest first. O(log n + k) via idx_audit_entity."""
        rows = await self._fetch(
            "SELECT action, actor, before, after, at FROM audit_log "
            "WHERE entity = ? AND entity_id = ? ORDER BY id",
            (entity, entity_id),
        )
        return [AuditEntry(**dict(row)) for row in rows]

    async def geocode_cache_get(self, query: str) -> tuple[float | None, float | None] | None:
        """Cached (lat, lng) for a normalised query; (None, None) is a cached miss. O(log n)."""
        rows = await self._fetch("SELECT lat, lng FROM geocode_cache WHERE query = ?", (query,))
        return (rows[0]["lat"], rows[0]["lng"]) if rows else None

    async def user_by_email(self, email: str) -> sqlite3.Row | None:
        rows = await self._fetch("SELECT id, name, email, password_hash FROM users WHERE email = ?", (email,))
        return rows[0] if rows else None

    async def user_by_id(self, user_id: str) -> sqlite3.Row | None:
        rows = await self._fetch("SELECT id, name, email FROM users WHERE id = ?", (user_id,))
        return rows[0] if rows else None

    async def table_names(self) -> list[str]:
        rows = await self._fetch("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
        return [row["name"] for row in rows]
