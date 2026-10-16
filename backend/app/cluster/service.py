"""Incident lifecycle: assign decided reports to incidents, merge twins, split, restore.

All mutations run under one lock and inside one DB transaction per batch, so the
in-memory index, the per-incident metadata and SQLite never disagree.
"""

import asyncio
import json
import time
import uuid
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np

from app.cluster.geocode import GeoPoint
from app.cluster.index import IncidentIndex, Vector
from app.db import Database
from app.decision.rules import ESCALATION
from app.models import Department, DecisionResult, Incident, IncidentStatus, Report

ESCALATE_AFTER_REPORTS = 10
DEPARTMENT_LABEL: dict[str, str] = {
    "fire": "Fire",
    "police": "Police",
    "medical": "Medical",
    "disaster": "Disaster",
    "utilities": "Utilities",
    "none": "Unclassified",
}


@dataclass(frozen=True)
class Placed:
    """A decided report with its location and embedding (pipeline stage 1 output)."""

    report: Report
    result: DecisionResult
    vector: Vector
    location_text: str | None
    point: GeoPoint | None


@dataclass
class IncidentMeta:
    first_seen: float
    departments: Counter[str] = field(default_factory=Counter)
    max_severity: int = 1
    escalated: bool = False
    hazards: dict[str, None] = field(default_factory=dict)
    location_text: str | None = None
    location_confirmed: bool = False
    status: IncidentStatus = "open"
    briefing: list[str] | None = None

    def add(self, report: Report, location_text: str | None, located: bool) -> None:
        """Fold one report in. O(L)."""
        decision = report.decision
        if decision is not None:
            self.departments[decision.department] += 1
            self.max_severity = max(self.max_severity, decision.severity)
            self.hazards.update(dict.fromkeys(decision.hazards))
        self.escalated = self.escalated or bool(ESCALATION.search(report.raw_text))
        if located and not self.location_confirmed:
            self.location_text, self.location_confirmed = location_text, True
        elif self.location_text is None:
            self.location_text = location_text

    def absorb(self, other: "IncidentMeta") -> None:
        self.first_seen = min(self.first_seen, other.first_seen)
        self.departments.update(other.departments)
        self.max_severity = max(self.max_severity, other.max_severity)
        self.escalated = self.escalated or other.escalated
        self.hazards.update(other.hazards)
        if other.location_confirmed and not self.location_confirmed:
            self.location_text, self.location_confirmed = other.location_text, True

    @property
    def department(self) -> Department:
        ranked = [d for d, _ in self.departments.most_common() if d != "none"]
        return ranked[0] if ranked else "none"  # type: ignore[return-value]

    def severity(self, report_count: int) -> int:
        """Highest report severity, +1 (cap 5) past 10 reports or on escalating details."""
        bump = report_count > ESCALATE_AFTER_REPORTS or self.escalated
        return min(5, self.max_severity + (1 if bump else 0))


def _new_incident_id() -> str:
    return f"i_{uuid.uuid4().hex}"


def _vector(blob: bytes) -> Vector:
    return np.frombuffer(blob, dtype=np.float32).copy()


@dataclass
class AssignResult:
    reports: list[Report]
    created: list[Incident]
    updated: list[Incident]


class IncidentService:
    def __init__(self, db: Database, index: IncidentIndex, clock: Callable[[], float] = time.time) -> None:
        self._db = db
        self._index = index
        self._clock = clock
        self._meta: dict[str, IncidentMeta] = {}
        self._lock = asyncio.Lock()

    def snapshot(self, incident_id: str, status: IncidentStatus | None = None) -> Incident:
        """Current state of an indexed incident. O(h) for h hazards."""
        meta = self._meta[incident_id]
        inc = self._index.get(incident_id)
        assert inc is not None
        return Incident(
            id=incident_id,
            title=f"{DEPARTMENT_LABEL[meta.department]} · {meta.location_text or 'location unconfirmed'}",
            department=meta.department,
            severity=meta.severity(inc.count),
            status=status or meta.status,
            lat=inc.lat,
            lng=inc.lng,
            location_text=meta.location_text,
            location_confirmed=meta.location_confirmed,
            report_count=inc.count,
            first_seen=meta.first_seen,
            last_updated=inc.last_updated,
            linked_hazards=list(meta.hazards),
            briefing=meta.briefing,
        )

    async def restore(self) -> int:
        """Reload open incidents still inside the clustering window. O(r) over their reports."""
        since = self._clock() - self._index.window_s
        restored = 0
        for incident, centroid in await self._db.open_incidents_since(since):
            if centroid is None:
                continue
            meta = IncidentMeta(first_seen=incident.first_seen, briefing=incident.briefing)
            for report, _ in await self._db.incident_reports(incident.id):
                meta.add(report, report.location_text, report.lat is not None)
            self._meta[incident.id] = meta
            self._index.add(
                incident.id, _vector(centroid), incident.department, incident.lat, incident.lng,
                count=max(1, incident.report_count), updated_at=incident.last_updated,
            )
            restored += 1
        return restored

    async def assign(self, items: Sequence[Placed]) -> AssignResult:
        """Cluster one decided batch and persist everything atomically.

        Per report: O(k·d) candidate scoring plus O(k·d) twin check, O(d + log n) update.
        """
        async with self._lock, self._db.transaction():
            await self._db.save_decisions([(p.report.id, p.result) for p in items])
            owner: dict[str, str] = {}
            redirect: dict[str, str] = {}
            created: set[str] = set()
            touched: set[str] = set()
            merged: list[Incident] = []
            moves: list[tuple[str, str]] = []
            decided: list[Report] = []
            audit: list[tuple[str, str, str, str, str | None, str | None]] = []
            for item in items:
                report = item.report.model_copy(
                    update={
                        "decision": item.result.decision,
                        "confidence": item.result.confidence,
                        "source": item.result.source,
                        "flags": item.result.rules_fired,
                        "location_text": item.location_text,
                        "lat": item.point.lat if item.point else None,
                        "lng": item.point.lng if item.point else None,
                    }
                )
                incident_id = self._place(report, item, created)
                touched.add(incident_id)
                twin = self._index.find_twin(incident_id)
                if twin is not None:
                    keep, gone = self._merge(incident_id, twin.incident_id)
                    merged.append(self.snapshot_from(gone, keep))
                    del self._meta[gone]
                    redirect[gone] = keep
                    created.discard(gone)
                    touched.discard(gone)
                    touched.add(keep)
                    moves.append((gone, keep))
                    audit.append(("incident", gone, "merged", "clusterer", None, json.dumps({"into": keep, "score": twin.score})))
                    incident_id = keep
                owner[report.id] = incident_id
                decided.append(report)

            def resolve(incident_id: str) -> str:
                while incident_id in redirect:
                    incident_id = redirect[incident_id]
                return incident_id

            current = [self.snapshot(i) for i in touched]
            # Incidents first: report rows reference them by foreign key.
            await self._db.upsert_incidents(
                [(i, self._index.get(i.id).centroid.tobytes()) for i in current]  # type: ignore[union-attr]
                + [(i, None) for i in merged]
            )
            for gone, keep in moves:
                await self._db.move_reports(gone, resolve(keep))
            placed = {p.report.id: p for p in items}
            await self._db.save_report_placement(
                [
                    (
                        resolve(owner[r.id]),
                        r.location_text,
                        r.lat,
                        r.lng,
                        placed[r.id].vector.astype(np.float32).tobytes(),
                        r.id,
                    )
                    for r in decided
                ]
            )
            decided = [r.model_copy(update={"incident_id": resolve(owner[r.id])}) for r in decided]
            audit += [("incident", i, "created", "clusterer", None, None) for i in created]
            await self._db.audit(audit)
        return AssignResult(
            reports=decided,
            created=[i for i in current if i.id in created],
            updated=[i for i in current if i.id not in created] + merged,
        )

    def snapshot_from(self, gone: str, keep: str) -> Incident:
        """Final state of an incident absorbed into ``keep`` (status ``merged``)."""
        meta = self._meta[gone]
        return Incident(
            id=gone,
            title=f"{DEPARTMENT_LABEL[meta.department]} · merged",
            department=meta.department,
            severity=meta.severity(0),
            status="merged",
            lat=None,
            lng=None,
            location_text=meta.location_text,
            location_confirmed=meta.location_confirmed,
            report_count=0,
            first_seen=meta.first_seen,
            last_updated=self._clock(),
            linked_hazards=list(meta.hazards),
            briefing=[f"Merged into {keep}"],
        )

    def _place(self, report: Report, item: Placed, created: set[str]) -> str:
        assert report.decision is not None
        lat, lng = report.lat, report.lng
        match = self._index.best_match(item.vector, report.decision.department, lat, lng)
        if match is None:
            incident_id = _new_incident_id()
            self._index.add(incident_id, item.vector, report.decision.department, lat, lng)
            self._meta[incident_id] = IncidentMeta(first_seen=report.received_at)
            created.add(incident_id)
        else:
            incident_id = match.incident_id
            self._index.join(incident_id, item.vector, lat, lng)
        self._meta[incident_id].add(report, item.location_text, lat is not None)
        return incident_id

    def _merge(self, a: str, b: str) -> tuple[str, str]:
        """Merge the smaller incident into the larger; returns (keep, gone). O(d + log n)."""
        inc_a, inc_b = self._index.get(a), self._index.get(b)
        assert inc_a is not None and inc_b is not None
        keep, gone = (a, b) if inc_a.count >= inc_b.count else (b, a)
        self._index.merge(keep, gone)
        self._meta[keep].absorb(self._meta[gone])
        return keep, gone

    async def split(self, incident_id: str, report_id: str) -> tuple[Incident, Incident]:
        """Move one report into a new incident; both incidents are recomputed. O(r·L)."""
        async with self._lock, self._db.transaction():
            found = await self._db.report(report_id)
            if found is None or found[0].incident_id != incident_id or found[1] is None:
                raise LookupError("report is not part of this incident")
            report, blob = found
            if incident_id not in self._index or report.decision is None:
                raise LookupError("incident is no longer open for clustering")
            vector = _vector(blob)
            remaining = [r for r, _ in await self._db.incident_reports(incident_id) if r.id != report_id]
            if not remaining:
                raise ValueError("an incident with one report cannot be split")
            self._index.remove_report(incident_id, vector)
            self._meta[incident_id] = self._rebuild(remaining)
            located = [r for r in remaining if r.lat is not None and r.lng is not None]
            self._index.relocate(
                incident_id,
                sum(r.lat for r in located) / len(located) if located else None,  # type: ignore[misc]
                sum(r.lng for r in located) / len(located) if located else None,  # type: ignore[misc]
                len(located),
            )
            new_id = _new_incident_id()
            self._index.add(new_id, vector, report.decision.department, report.lat, report.lng)
            self._meta[new_id] = self._rebuild([report])
            old, new = self.snapshot(incident_id), self.snapshot(new_id)
            await self._db.upsert_incidents(
                [(i, self._index.get(i.id).centroid.tobytes()) for i in (old, new)]  # type: ignore[union-attr]
            )
            await self._db.set_report_incident(report_id, new_id)
            detail = json.dumps({"report_id": report_id, "new_incident": new_id})
            await self._db.audit(
                [
                    ("incident", incident_id, "split", "dispatcher", None, detail),
                    ("incident", new_id, "created", "dispatcher", None, detail),
                ]
            )
        return old, new

    @staticmethod
    def _rebuild(reports: Sequence[Report]) -> IncidentMeta:
        meta = IncidentMeta(first_seen=min(r.received_at for r in reports))
        for report in reports:
            meta.add(report, report.location_text, report.lat is not None)
        return meta
