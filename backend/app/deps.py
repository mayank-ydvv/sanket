"""FastAPI dependency getters for objects created in the app lifespan."""

from fastapi import Request

from app.config import Settings
from app.db import Database
from app.worker import PipelineWorker


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_db(request: Request) -> Database:
    db: Database = request.app.state.db
    return db


def get_worker(request: Request) -> PipelineWorker:
    worker: PipelineWorker = request.app.state.worker
    return worker
