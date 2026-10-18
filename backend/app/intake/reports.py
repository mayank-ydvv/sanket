"""Text intake: ``POST /reports`` and the recent-reports listing."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel

from app.auth_api import User, current_user
from app.db import Database
from app.deps import get_db
from app.intake.service import Intake
from app.models import Report, ReportIn

router = APIRouter(tags=["intake"])


class Accepted(BaseModel):
    id: str


@router.post("/reports", status_code=status.HTTP_202_ACCEPTED)
async def create_report(body: ReportIn, request: Request) -> Accepted:
    """Citizen intake (public, no login): persist, queue for triage, return at once. O(L)."""
    intake: Intake = request.app.state.intake
    report = await intake.submit(body.text, body.channel, body.caller)
    return Accepted(id=report.id)


@router.get("/reports")
async def list_reports(
    db: Annotated[Database, Depends(get_db)],
    _user: Annotated[User | None, Depends(current_user)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[Report]:
    return await db.recent_reports(limit)
