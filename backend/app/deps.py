"""FastAPI dependency getters for objects created in the app lifespan."""

from fastapi import Request

from app.cluster.service import IncidentService
from app.config import Settings
from app.db import Database
from app.worker import PipelineWorker


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_db(request: Request) -> Database:
    db: Database = request.app.state.db
    return db


def get_worker(request: Request) -> PipelineWorker[object]:
    worker: PipelineWorker[object] = request.app.state.worker
    return worker


def get_incidents(request: Request) -> IncidentService:
    incidents: IncidentService = request.app.state.incidents
    return incidents
