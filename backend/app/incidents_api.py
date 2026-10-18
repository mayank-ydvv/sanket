"""Incident endpoints: ranked list, detail, and the dispatcher's confirm / override / split / ack."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.alerts.service import AlertService
from app.cluster.service import IncidentService
from app.db import Database
from app.deps import get_alerts, get_broadcaster, get_db, get_incidents
from app.models import Alert, Incident, IncidentDetail, IncidentStatus, OverrideRequest
from app.translate import MAX_BATCH, Translator
from app.ws import Broadcaster

router = APIRouter(prefix="/incidents", tags=["incidents"])
alerts_router = APIRouter(tags=["alerts"])
DISPATCHER = "dispatcher"


class SplitRequest(BaseModel):
    report_id: str


class SplitResult(BaseModel):
    original: Incident
    new: Incident


class TranslateResult(BaseModel):
    translated: int
    pending: int  # still untranslated (provider unavailable, or more than one batch)
    available: bool


class MergeRequest(BaseModel):
    into: str


class MergeResult(BaseModel):
    merged: Incident
    kept: Incident


@router.get("")
async def list_incidents(
    db: Annotated[Database, Depends(get_db)],
    status: IncidentStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[Incident]:
    """Ranked by severity, then longest waiting. All statuses except merged by default."""
    incidents = await db.incidents(status, limit + 50)
    return [i for i in incidents if status or i.status != "merged"][:limit]


@router.get("/{incident_id}")
async def incident_detail(incident_id: str, db: Annotated[Database, Depends(get_db)]) -> IncidentDetail:
    incident = await db.incident(incident_id)
    if incident is None:
        raise HTTPException(404, "incident not found")
    return IncidentDetail(
        incident=incident,
        reports=[r for r, _ in await db.incident_reports(incident_id)],
        audit=await db.audit_for("incident", incident_id),
        alerts=await db.alerts_for(incident_id),
    )


@router.post("/{incident_id}/confirm")
async def confirm(
    incident_id: str, alerts: Annotated[AlertService, Depends(get_alerts)]
) -> Alert | None:
    """One-click dispatch. Returns the alert sent, or null if one is already live."""
    try:
        return await alerts.dispatch(incident_id, triggered_by=DISPATCHER)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{incident_id}/override")
async def override(
    incident_id: str,
    body: OverrideRequest,
    incidents: Annotated[IncidentService, Depends(get_incidents)],
    alerts: Annotated[AlertService, Depends(get_alerts)],
    broadcaster: Annotated[Broadcaster, Depends(get_broadcaster)],
) -> Incident:
    try:
        incident = await incidents.override(incident_id, body, actor=DISPATCHER)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    broadcaster.publish("incident.updated", incident.model_dump(mode="json"))
    await alerts.reroute_if_department_changed(incident)
    return incident


@router.post("/{incident_id}/ack")
async def acknowledge(incident_id: str, alerts: Annotated[AlertService, Depends(get_alerts)]) -> Alert:
    """Responding unit acknowledged: stops the escalation timer."""
    try:
        return await alerts.acknowledge(incident_id, actor=DISPATCHER)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{incident_id}/merge")
async def merge_incident(
    incident_id: str,
    body: MergeRequest,
    request: Request,
    incidents: Annotated[IncidentService, Depends(get_incidents)],
    broadcaster: Annotated[Broadcaster, Depends(get_broadcaster)],
) -> MergeResult:
    """Dispatcher confirms a merge (e.g. one the reasoning layer suggested)."""
    try:
        merged, kept = await incidents.merge_into(incident_id, body.into, actor=DISPATCHER)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    broadcaster.publish("incident.updated", merged.model_dump(mode="json"))
    broadcaster.publish("incident.updated", kept.model_dump(mode="json"))
    if request.app.state.reasoner is not None:
        request.app.state.reasoner.consider([kept])
    return MergeResult(merged=merged, kept=kept)


@router.post("/{incident_id}/split")
async def split_incident(
    incident_id: str,
    body: SplitRequest,
    incidents: Annotated[IncidentService, Depends(get_incidents)],
    broadcaster: Annotated[Broadcaster, Depends(get_broadcaster)],
) -> SplitResult:
    """Move one report out into its own incident (dispatcher correction)."""
    try:
        original, new = await incidents.split(incident_id, body.report_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    broadcaster.publish("incident.updated", original.model_dump(mode="json"))
    broadcaster.publish("incident.created", new.model_dump(mode="json"))
    return SplitResult(original=original, new=new)


@router.post("/{incident_id}/translate")
async def translate_incident(
    incident_id: str,
    request: Request,
    db: Annotated[Database, Depends(get_db)],
    broadcaster: Annotated[Broadcaster, Depends(get_broadcaster)],
) -> TranslateResult:
    """English for this incident's reports that have none yet (newest first, one batch).

    Called when a dispatcher opens the incident; each report is translated at most once.
    """
    if await db.incident(incident_id) is None:
        raise HTTPException(404, "incident not found")
    translator: Translator | None = request.app.state.translator
    inflight: set[str] = request.app.state.translating
    todo = [
        r
        for r, _ in await db.incident_reports(incident_id)
        if r.english_gloss is None and r.raw_text.strip() and r.id not in inflight
    ][-MAX_BATCH:]
    if not todo or translator is None or not translator.available:
        return TranslateResult(translated=0, pending=len(todo), available=translator is not None and translator.available)
    inflight.update(r.id for r in todo)
    try:
        results = await translator.translate([r.raw_text for r in todo])
    finally:
        inflight.difference_update(r.id for r in todo)
    done = [(report, english) for report, english in zip(todo, results, strict=True) if english is not None]
    async with db.transaction():
        await db.save_glosses([(report.id, english) for report, english in done])
    for report, english in done:
        broadcaster.publish("report.updated", report.model_copy(update={"english_gloss": english}).model_dump(mode="json"))
    return TranslateResult(translated=len(done), pending=len(todo) - len(done), available=True)


@alerts_router.get("/alerts")
async def recent_alerts(
    db: Annotated[Database, Depends(get_db)], limit: Annotated[int, Query(ge=1, le=1000)] = 300
) -> list[Alert]:
    return await db.recent_alerts(limit)
