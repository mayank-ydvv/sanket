"""Incident lifecycle: assign, revise, merge twins, split, override, restore.

All mutations run under one lock and inside one DB transaction per call, so the
in-memory index, per-incident metadata and SQLite never disagree. Incidents that
have aged out of the clustering index stay on the board; their metadata is
rebuilt from their reports on demand.
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
from app.models import (
    DecisionResult,
    Department,
    Incident,
    IncidentStatus,
    Lane,
    OverrideRequest,
    Report,
)

ESCALATE_AFTER_REPORTS = 10
PRANK_AT = 0.5
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
    refining: bool = False


@dataclass(frozen=True)
class Revision:
    """An LLM-revised decision for a report that is already on the board."""

    report_id: str
    result: DecisionResult
    vector: Vector
    location_text: str | None
    point: GeoPoint | None


@dataclass
class IncidentMeta:
    """Everything derived from an incident's reports. ``add`` is O(L) per report."""

    first_seen: float
    departments: Counter[str] = field(default_factory=Counter)
    max_severity: int = 1
    escalated: bool = False
    hazards: dict[str, None] = field(default_factory=dict)
    location_text: str | None = None
    location_confirmed: bool = False
    status: IncidentStatus = "open"
    briefing: list[str] | None = None
    overrides: dict[str, str | int] = field(default_factory=dict)
    combined_risk: str | None = None
    risk_hazards: list[str] = field(default_factory=list)
    merge_suggestions: list[str] = field(default_factory=list)
    reasoned_at: float | None = None
    lanes: Counter[str] = field(default_factory=Counter)
    confidence_sum: float = 0.0
    decided: int = 0
    silent_sos: int = 0
    pranks: int = 0
    review: int = 0

    def add(self, report: Report, located: bool) -> None:
        decision = report.decision
        if decision is not None:
            self.departments[decision.department] += 1
            self.max_severity = max(self.max_severity, decision.severity)
            self.hazards.update(dict.fromkeys(decision.hazards))
            self.lanes[decision.lane] += 1
            self.confidence_sum += decision.confidence
            self.decided += 1
            self.silent_sos += decision.silent_sos
            self.pranks += decision.prank_score >= PRANK_AT
            self.review += decision.needs_human_review
        self.escalated = self.escalated or bool(ESCALATION.search(report.raw_text))
        if located and not self.location_confirmed:
            self.location_text, self.location_confirmed = report.location_text, True
        elif self.location_text is None:
            self.location_text = report.location_text

    def absorb(self, other: "IncidentMeta") -> None:
        self.first_seen = min(self.first_seen, other.first_seen)
        self.departments.update(other.departments)
        self.lanes.update(other.lanes)
        self.max_severity = max(self.max_severity, other.max_severity)
        self.escalated = self.escalated or other.escalated
        self.hazards.update(other.hazards)
        self.confidence_sum += other.confidence_sum
        self.decided += other.decided
        self.silent_sos += other.silent_sos
        self.pranks += other.pranks
        self.review += other.review
        if other.status == "dispatched":
            self.status = "dispatched"
        if other.location_confirmed and not self.location_confirmed:
            self.location_text, self.location_confirmed = other.location_text, True

    @property
    def department(self) -> Department:
        if "department" in self.overrides:
            return self.overrides["department"]  # type: ignore[return-value]
        ranked = [d for d, _ in self.departments.most_common() if d != "none"]
        return ranked[0] if ranked else "none"  # type: ignore[return-value]

    def severity(self, report_count: int) -> int:
        """Highest report severity, +1 (cap 5) past 10 reports or on escalating details."""
        if "severity" in self.overrides:
            return int(self.overrides["severity"])
        bump = report_count > ESCALATE_AFTER_REPORTS or self.escalated
        return min(5, self.max_severity + (1 if bump else 0))

    @property
    def lane(self) -> Lane:
        """Silent SOS always goes to a human. Otherwise one report that clears the
        auto-dispatch gate is enough to dispatch; mostly-flagged incidents go to review."""
        if self.silent_sos or not self.decided:
            return "review"
        if self.lanes["auto"]:
            return "auto"
        return "review" if self.review * 2 >= self.decided else "confirm"


# State set by dispatchers or the reasoning layer, not derivable from the reports.
CARRIED = ("status", "briefing", "overrides", "combined_risk", "risk_hazards", "merge_suggestions", "reasoned_at")


def inherit(meta: IncidentMeta, source: "IncidentMeta | Incident") -> IncidentMeta:
    """Copy carried state onto metadata rebuilt from reports. O(1)."""
    for name in CARRIED:
        value = getattr(source, name)
        setattr(meta, name, value.copy() if isinstance(value, dict | list) else value)
    return meta


def _new_incident_id() -> str:
    return f"i_{uuid.uuid4().hex}"


def _vector(blob: bytes) -> Vector:
    return np.frombuffer(blob, dtype=np.float32).copy()


@dataclass
class ChangeSet:
    reports: list[Report] = field(default_factory=list)
    created: list[Incident] = field(default_factory=list)
    updated: list[Incident] = field(default_factory=list)


class IncidentService:
    def __init__(self, db: Database, index: IncidentIndex, clock: Callable[[], float] = time.time) -> None:
        self._db = db
        self._index = index
        self._clock = clock
        self._meta: dict[str, IncidentMeta] = {}
        self._lock = asyncio.Lock()

    # -- composing snapshots ---------------------------------------------------

    def _compose(self, incident_id: str, meta: IncidentMeta, base: Incident | None = None) -> Incident:
        """Incident from metadata plus index geometry (or the stored row if not indexed)."""
        inc = self._index.get(incident_id)
        count = inc.count if inc else (base.report_count if base else 0)
        return Incident(
            id=incident_id,
            title=f"{DEPARTMENT_LABEL[meta.department]} · {meta.location_text or 'location unconfirmed'}",
            department=meta.department,
            severity=meta.severity(count),
            status=meta.status,
            lat=inc.lat if inc else (base.lat if base else None),
            lng=inc.lng if inc else (base.lng if base else None),
            location_text=meta.location_text,
            location_confirmed=meta.location_confirmed,
            report_count=count,
            first_seen=meta.first_seen,
            last_updated=inc.last_updated if inc else (base.last_updated if base else self._clock()),
            linked_hazards=list(meta.hazards),
            briefing=meta.briefing,
            combined_risk=meta.combined_risk,
            risk_hazards=meta.risk_hazards,
            merge_suggestions=meta.merge_suggestions,
            reasoned_at=meta.reasoned_at,
            lane=meta.lane,
            confidence=meta.confidence_sum / meta.decided if meta.decided else 0.0,
            silent_sos=meta.silent_sos > 0,
            prank_suspected=meta.decided > 0 and meta.pranks * 2 > meta.decided,
            needs_review=meta.review > 0,
            overrides=meta.overrides,
        )

    def snapshot(self, incident_id: str) -> Incident:
        return self._compose(incident_id, self._meta[incident_id])

    async def _meta_for(self, incident_id: str) -> tuple[IncidentMeta, Incident]:
        """Cached metadata, or rebuilt from the stored reports. O(r) on a cache miss."""
        stored = await self._db.incident(incident_id)
        if stored is None:
            raise LookupError("incident not found")
        if incident_id not in self._meta:
            meta = self._rebuild([r for r, _ in await self._db.incident_reports(incident_id)])
            inherit(meta, stored)
            self._meta[incident_id] = meta
        return self._meta[incident_id], stored

    @staticmethod
    def _rebuild(reports: Sequence[Report]) -> IncidentMeta:
        meta = IncidentMeta(first_seen=min((r.received_at for r in reports), default=time.time()))
        for report in reports:
            meta.add(report, report.lat is not None)
        return meta

    def _centroid_row(self, incident: Incident) -> tuple[Incident, bytes | None]:
        inc = self._index.get(incident.id)
        return incident, inc.centroid.tobytes() if inc else None

    # -- restore ---------------------------------------------------------------

    async def restore(self) -> int:
        """Reload open incidents still inside the clustering window. O(r) over their reports."""
        since = self._clock() - self._index.window_s
        restored = 0
        for incident, centroid in await self._db.open_incidents_since(since):
            if centroid is None:
                continue
            meta = self._rebuild([r for r, _ in await self._db.incident_reports(incident.id)])
            inherit(meta, incident)
            self._meta[incident.id] = meta
            self._index.add(
                incident.id, _vector(centroid), incident.department, incident.lat, incident.lng,
                count=max(1, incident.report_count), updated_at=incident.last_updated,
            )
            restored += 1
        return restored

    # -- assignment ------------------------------------------------------------

    async def assign(self, items: Sequence[Placed]) -> ChangeSet:
        """Cluster one decided batch and persist it atomically.

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
                        "refining": item.refining,
                    }
                )
                incident_id = self._place(report, item.vector, created)
                touched.add(incident_id)
                twin = None if item.result.decision.silent_sos else self._index.find_twin(incident_id)
                if twin is not None:
                    keep, gone = self._merge(incident_id, twin.incident_id)
                    merged.append(self._merged_snapshot(gone, keep))
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
            await self._db.upsert_incidents([self._centroid_row(i) for i in current] + [(i, None) for i in merged])
            for gone, keep in moves:
                await self._db.move_reports(gone, resolve(keep))
            placed = {p.report.id: p for p in items}
            await self._db.save_report_placement(
                [
                    (resolve(owner[r.id]), r.location_text, r.lat, r.lng, placed[r.id].vector.astype(np.float32).tobytes(), r.id)
                    for r in decided
                ]
            )
            audit += [("incident", i, "created", "clusterer", None, None) for i in created]
            await self._db.audit(audit)
        return ChangeSet(
            reports=[r.model_copy(update={"incident_id": resolve(owner[r.id])}) for r in decided],
            created=[i for i in current if i.id in created],
            updated=[i for i in current if i.id not in created] + merged,
        )

    def _place(self, report: Report, vector: Vector, created: set[str]) -> str:
        """Join the best-matching incident or start one. A silent SOS always starts its
        own: with no words and often no location, it must never be folded into
        another caller's incident."""
        assert report.decision is not None
        lat, lng = report.lat, report.lng
        if report.decision.silent_sos:
            incident_id = _new_incident_id()
            # A private pool key: no other report's candidate lookup can reach it.
            self._index.add(incident_id, vector, f"silent:{incident_id}", lat, lng)
            self._meta[incident_id] = IncidentMeta(first_seen=report.received_at)
            self._meta[incident_id].add(report, lat is not None)
            created.add(incident_id)
            return incident_id
        match = self._index.best_match(vector, report.decision.department, lat, lng)
        if match is None:
            incident_id = _new_incident_id()
            self._index.add(incident_id, vector, report.decision.department, lat, lng)
            self._meta[incident_id] = IncidentMeta(first_seen=report.received_at)
            created.add(incident_id)
        else:
            incident_id = match.incident_id
            self._index.join(incident_id, vector, lat, lng)
        self._meta[incident_id].add(report, lat is not None)
        return incident_id

    def _merge(self, a: str, b: str) -> tuple[str, str]:
        """Merge the smaller incident into the larger; returns (keep, gone). O(d + log n)."""
        inc_a, inc_b = self._index.get(a), self._index.get(b)
        assert inc_a is not None and inc_b is not None
        keep, gone = (a, b) if inc_a.count >= inc_b.count else (b, a)
        self._index.merge(keep, gone)
        self._meta[keep].absorb(self._meta[gone])
        return keep, gone

    def _merged_snapshot(self, gone: str, keep: str) -> Incident:
        snapshot = self._compose(gone, self._meta[gone])
        return snapshot.model_copy(
            update={"status": "merged", "report_count": 0, "lat": None, "lng": None, "briefing": [f"Merged into {keep}"]}
        )

    # -- LLM revisions ---------------------------------------------------------

    async def revise(self, revisions: Sequence[Revision]) -> ChangeSet:
        """Apply LLM-revised decisions to reports already on the board.

        A report was clustered with its *local* decision. If the revision changes its
        department or finally locates it, the report is re-placed: taken out of its
        incident (O(d)) and matched again (O(k·d)) — joining the right incident, or
        keeping its own if it was alone and nothing better exists. Otherwise only its
        embedding is swapped in the centroid. Touched incidents are rebuilt from their
        reports (O(r)).
        """
        changes = ChangeSet()
        async with self._lock, self._db.transaction():
            touched: set[str] = set()
            moves: list[tuple[str, str]] = []
            emptied: dict[str, str] = {}
            audit: list[tuple[str, str, str, str, str | None, str | None]] = []
            for rev in revisions:
                found = await self._db.report(rev.report_id)
                if found is None or found[0].incident_id is None or found[0].decision is None:
                    continue
                report, blob = found
                current = report.incident_id
                assert current is not None
                if report.lat is None and rev.point is not None:
                    await self._db.update_report_location(report.id, rev.location_text, rev.point.lat, rev.point.lng)
                    report = report.model_copy(
                        update={"lat": rev.point.lat, "lng": rev.point.lng, "location_text": rev.location_text}
                    )
                await self._db.update_report_embedding(report.id, rev.vector.astype(np.float32).tobytes())
                touched.add(current)
                moved = rev.result.decision.department != found[0].decision.department or (
                    found[0].lat is None and report.lat is not None
                )
                if blob is None or current not in self._index:
                    continue
                if not moved:
                    self._index.swap_vector(current, _vector(blob), rev.vector)
                    continue
                target = self._replace(current, _vector(blob), rev, report)
                if target != current:
                    moves.append((report.id, target))
                    touched.add(target)
                    audit.append(("incident", target, "report_moved", "llm-revision", current, json.dumps({"report_id": report.id})))
                    if current not in self._index:
                        emptied[current] = target
            # Compared against the prior decisions above, so saved only now.
            await self._db.save_decisions([(r.report_id, r.result) for r in revisions], action="revised")
            # New incidents must exist before reports point at them.
            for incident_id in touched - set(emptied):
                if await self._db.incident(incident_id) is None:
                    await self._db.upsert_incidents([self._centroid_row(self.snapshot(incident_id))])
            for report_id, target in moves:
                await self._db.set_report_incident(report_id, target)
            revised_ids = {r.report_id for r in revisions}
            for incident_id in touched:
                rows = [r for r, _ in await self._db.incident_reports(incident_id)]
                old = self._meta.get(incident_id)
                if incident_id in emptied or not rows:
                    if old is not None:
                        snapshot = self._compose(incident_id, old).model_copy(
                            update={"status": "merged", "report_count": 0, "lat": None, "lng": None,
                                    "briefing": [f"Merged into {emptied.get(incident_id, 'another incident')}"]}
                        )
                        changes.updated.append(snapshot)
                        del self._meta[incident_id]
                    continue
                meta = self._rebuild(rows)
                if old is not None:
                    inherit(meta, old)
                self._meta[incident_id] = meta
                changes.updated.append(self._compose(incident_id, meta, await self._db.incident(incident_id)))
                changes.reports += [r for r in rows if r.id in revised_ids]
            await self._db.upsert_incidents([self._centroid_row(i) for i in changes.updated])
            await self._db.audit(audit)
        return changes

    def _replace(self, current: str, old_vector: Vector, rev: Revision, report: Report) -> str:
        """Re-cluster one report under its revised decision; returns its incident id."""
        department = rev.result.decision.department
        remaining = self._index.remove_report(current, old_vector)
        match = self._index.best_match(rev.vector, department, report.lat, report.lng)
        if match is not None:
            self._index.join(match.incident_id, rev.vector, report.lat, report.lng)
            self._meta.setdefault(match.incident_id, IncidentMeta(first_seen=report.received_at))
            return match.incident_id
        if remaining is None:  # it was alone: keep its incident, now under the right department
            self._index.add(current, rev.vector, department, report.lat, report.lng)
            return current
        incident_id = _new_incident_id()
        self._index.add(incident_id, rev.vector, department, report.lat, report.lng)
        self._meta[incident_id] = IncidentMeta(first_seen=report.received_at)
        self._meta[incident_id].add(
            report.model_copy(update={"decision": rev.result.decision}), report.lat is not None
        )
        return incident_id

    # -- dispatcher actions ----------------------------------------------------

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
            old_meta = self._meta.get(incident_id)
            meta = self._rebuild(remaining)
            if old_meta is not None:
                inherit(meta, old_meta)
            self._meta[incident_id] = meta
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
            await self._db.upsert_incidents([self._centroid_row(i) for i in (old, new)])
            await self._db.set_report_incident(report_id, new_id)
            detail = json.dumps({"report_id": report_id, "new_incident": new_id})
            await self._db.audit(
                [
                    ("incident", incident_id, "split", "dispatcher", None, detail),
                    ("incident", new_id, "created", "dispatcher", None, detail),
                ]
            )
        return old, new

    async def override(self, incident_id: str, request: OverrideRequest, actor: str) -> Incident:
        """Dispatcher sets department and/or severity. Before/after go to the audit log."""
        async with self._lock, self._db.transaction():
            meta, stored = await self._meta_for(incident_id)
            before = self._compose(incident_id, meta, stored)
            if request.department is not None:
                meta.overrides["department"] = request.department
            if request.severity is not None:
                meta.overrides["severity"] = request.severity
            after = self._compose(incident_id, meta, stored)
            await self._db.upsert_incidents([self._centroid_row(after)])
            await self._db.audit(
                [
                    (
                        "incident", incident_id, "override", actor,
                        before.model_dump_json(include={"department", "severity"}),
                        json.dumps({**after.model_dump(include={"department", "severity"}), "note": request.note}),
                    )
                ]
            )
        return after

    def nearby(self, incident_id: str, radius_km: float, window_s: float) -> list[Incident]:
        """Open incidents within ``radius_km`` updated in the last ``window_s``. O(k)."""
        since = self._clock() - window_s
        return [
            self.snapshot(i)
            for i in self._index.nearby(incident_id, radius_km, since)
            if i in self._meta
        ]

    async def reasoning_input(self, incident_id: str, max_reports: int) -> tuple[Incident, list[Report]]:
        """Current incident and its newest ``max_reports`` reports (oldest first)."""
        incident = await self.current(incident_id)
        reports = [r for r, _ in await self._db.incident_reports(incident_id)]
        return incident, reports[-max_reports:]

    async def apply_reasoning(
        self,
        incident_id: str,
        *,
        risk_hazards: list[str],
        combined_risk: str | None,
        merge_suggestions: list[str],
        briefing: list[str],
        actor: str,
        prompt_version: str,
    ) -> Incident:
        """Store the reasoning layer's output on an incident (audited with prompt version)."""
        async with self._lock, self._db.transaction():
            meta, stored = await self._meta_for(incident_id)
            meta.risk_hazards, meta.combined_risk = risk_hazards, combined_risk
            meta.merge_suggestions, meta.briefing = merge_suggestions, briefing or None
            meta.reasoned_at = self._clock()
            incident = self._compose(incident_id, meta, stored)
            await self._db.upsert_incidents([self._centroid_row(incident)])
            await self._db.audit(
                [
                    (
                        "incident", incident_id, "reasoned", actor, None,
                        json.dumps({
                            "prompt_version": prompt_version, "risk_hazards": risk_hazards,
                            "combined_risk": combined_risk, "merge_suggestions": merge_suggestions,
                            "briefing": briefing,
                        }, ensure_ascii=False),
                    )
                ]
            )
        return incident

    async def merge_into(self, gone: str, keep: str, actor: str) -> tuple[Incident, Incident]:
        """Dispatcher-confirmed merge of ``gone`` into ``keep``. O(r) to rebuild ``keep``."""
        if gone == keep:
            raise ValueError("an incident cannot be merged into itself")
        async with self._lock, self._db.transaction():
            gone_meta, gone_row = await self._meta_for(gone)
            keep_meta, _ = await self._meta_for(keep)
            if "merged" in (gone_meta.status, keep_meta.status):
                raise ValueError("incident already merged")
            if gone in self._index and keep in self._index:
                self._index.merge(keep, gone)
            else:
                self._index.drop(gone)
            await self._db.move_reports(gone, keep)
            rebuilt = inherit(self._rebuild([r for r, _ in await self._db.incident_reports(keep)]), keep_meta)
            rebuilt.merge_suggestions = [i for i in rebuilt.merge_suggestions if i != gone]
            if gone_meta.status == "dispatched":
                rebuilt.status = "dispatched"
            self._meta[keep] = rebuilt
            kept = self._compose(keep, rebuilt, await self._db.incident(keep))
            merged = self._compose(gone, gone_meta, gone_row).model_copy(
                update={"status": "merged", "report_count": 0, "lat": None, "lng": None, "briefing": [f"Merged into {keep}"]}
            )
            del self._meta[gone]
            await self._db.upsert_incidents([self._centroid_row(kept), (merged, None)])
            await self._db.audit([("incident", gone, "merged", actor, None, json.dumps({"into": keep}))])
        return merged, kept

    async def set_status(self, incident_id: str, status: IncidentStatus, actor: str, action: str) -> Incident:
        async with self._lock, self._db.transaction():
            meta, stored = await self._meta_for(incident_id)
            meta.status = status
            incident = self._compose(incident_id, meta, stored)
            await self._db.upsert_incidents([self._centroid_row(incident)])
            await self._db.audit([("incident", incident_id, action, actor, None, json.dumps({"status": status}))])
        return incident

    async def current(self, incident_id: str) -> Incident:
        meta, stored = await self._meta_for(incident_id)
        return self._compose(incident_id, meta, stored)
