"""Text intake: ``POST /reports`` and the recent-reports listing."""

import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel

from app.config import Settings
from app.db import Database
from app.deps import get_db, get_settings_dep, get_worker
from app.models import Report, ReportIn
from app.privacy import hash_caller
from app.worker import PipelineWorker

router = APIRouter(tags=["intake"])


class Accepted(BaseModel):
    id: str


@router.post("/reports", status_code=status.HTTP_202_ACCEPTED)
async def create_report(
    body: ReportIn,
    settings: Annotated[Settings, Depends(get_settings_dep)],
    db: Annotated[Database, Depends(get_db)],
    worker: Annotated[PipelineWorker, Depends(get_worker)],
) -> Accepted:
    """Persist the raw report, queue it for triage and return at once. O(L)."""
    report = Report(
        id=f"r_{uuid.uuid4().hex}",
        channel=body.channel,
        caller_hash=hash_caller(body.caller, settings.caller_salt),
        raw_text=body.text,
        received_at=time.time(),
    )
    await db.insert_report(report)
    worker.submit(report)
    return Accepted(id=report.id)


@router.get("/reports")
async def list_reports(
    db: Annotated[Database, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[Report]:
    return await db.recent_reports(limit)
