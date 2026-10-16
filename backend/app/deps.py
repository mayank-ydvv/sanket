"""FastAPI dependency getters for objects created in the app lifespan."""

from fastapi import Request

from app.alerts.service import AlertService
from app.cluster.service import IncidentService
from app.db import Database
from app.ws import Broadcaster


def get_db(request: Request) -> Database:
    db: Database = request.app.state.db
    return db


def get_incidents(request: Request) -> IncidentService:
    incidents: IncidentService = request.app.state.incidents
    return incidents


def get_alerts(request: Request) -> AlertService:
    alerts: AlertService = request.app.state.alerts
    return alerts


def get_broadcaster(request: Request) -> Broadcaster:
    broadcaster: Broadcaster = request.app.state.broadcaster
    return broadcaster
