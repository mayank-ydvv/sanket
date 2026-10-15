"""FastAPI application factory. Run with ``uvicorn app.main:create_app --factory``."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import ws
from app.config import Settings, get_settings
from app.db import Database
from app.decision.local import LocalClassifier
from app.decision.pipeline import DecisionPipeline
from app.intake import reports
from app.worker import PipelineWorker

log = logging.getLogger(__name__)


async def load_local_classifier(settings: Settings) -> LocalClassifier | None:
    """Load the trained model off the event loop; a missing model degrades to review-all."""
    path = settings.local_model_path
    if not path.exists():
        log.error("local model not found at %s; run `python -m scripts.train_local`", path)
        return None
    classifier = await asyncio.to_thread(LocalClassifier.load, path)
    log.info("loaded local classifier %s", classifier.model.version)
    return classifier


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Tests pass their own settings (temp DB, fixed salt)."""
    cfg = settings or get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = await Database.open(cfg.db_path)
        http = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))
        hub = ws.Hub()
        pipeline = DecisionPipeline(await load_local_classifier(cfg))
        worker = PipelineWorker(
            db, hub, pipeline.decide_batch, cfg.ingest_batch_size, cfg.ingest_batch_wait_ms / 1000
        )
        task = asyncio.create_task(worker.run(), name="pipeline-worker")
        app.state.settings = cfg
        app.state.db = db
        app.state.http = http
        app.state.hub = hub
        app.state.worker = worker
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            await http.aclose()
            await db.close()

    app = FastAPI(title="Sanket", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(reports.router)
    app.include_router(ws.router)
    return app
