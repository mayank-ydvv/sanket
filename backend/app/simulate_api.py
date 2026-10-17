"""Disaster mode endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.simulate import Scenario, SimulationRunner

router = APIRouter(prefix="/simulate", tags=["simulate"])


@router.post("/disaster", status_code=status.HTTP_202_ACCEPTED)
async def start_disaster(
    request: Request,
    n: Annotated[int, Query(ge=10, le=5000)] = 500,
    seconds: Annotated[float, Query(gt=0, le=600)] = 10.0,
    scenario: Scenario = "flood",
    seed: int = 7,
) -> dict[str, Any]:
    """Stream ``n`` generated reports into the real pipeline over ``seconds``."""
    runner: SimulationRunner = request.app.state.simulation
    try:
        return runner.start(scenario, n, seconds, seed).public()
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/status")
async def simulation_status(request: Request) -> dict[str, Any]:
    runner: SimulationRunner = request.app.state.simulation
    return runner.status.public()
