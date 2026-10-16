"""Incident endpoints: ranked list, detail with reports + audit trail, split."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.cluster.service import IncidentService
from app.db import Database
from app.deps import get_db, get_incidents
from app.models import Incident, IncidentDetail, IncidentStatus

router = APIRouter(prefix="/incidents", tags=["incidents"])


class SplitRequest(BaseModel):
    report_id: str


class SplitResult(BaseModel):
    original: Incident
    new: Incident


@router.get("")
async def list_incidents(
    db: Annotated[Database, Depends(get_db)],
    status: IncidentStatus | None = "open",
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[Incident]:
    """Ranked by severity, then longest waiting."""
    return await db.incidents(status, limit)


@router.get("/{incident_id}")
async def incident_detail(incident_id: str, db: Annotated[Database, Depends(get_db)]) -> IncidentDetail:
    incident = await db.incident(incident_id)
    if incident is None:
        raise HTTPException(404, "incident not found")
    reports = [r for r, _ in await db.incident_reports(incident_id)]
    return IncidentDetail(incident=incident, reports=reports, audit=await db.audit_for("incident", incident_id))


@router.post("/{incident_id}/split")
async def split_incident(
    incident_id: str,
    body: SplitRequest,
    request: Request,
    incidents: Annotated[IncidentService, Depends(get_incidents)],
) -> SplitResult:
    """Move one report out into its own incident (dispatcher correction)."""
    try:
        original, new = await incidents.split(incident_id, body.report_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    hub = request.app.state.hub
    await hub.broadcast("incident.updated", original.model_dump(mode="json"))
    await hub.broadcast("incident.created", new.model_dump(mode="json"))
    return SplitResult(original=original, new=new)
