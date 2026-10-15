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
from app.decision.factory import build_llm_decider
from app.decision.local import LocalClassifier
from app.decision.pipeline import DecisionPipeline
from app.decision.rules import PrankTracker, SafetyRules
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
        llm = build_llm_decider(cfg, http)
        if llm is None:
            log.warning("no LLM provider configured; uncertain reports keep their local decision")
        else:
            log.info("LLM chain: %s", " -> ".join(s.provider.name for s in llm.chain.slots))
        rules = SafetyRules(PrankTracker(cfg.prank_window_s, cfg.prank_min_reports))
        pipeline = DecisionPipeline(await load_local_classifier(cfg), llm, rules, cfg.conf_threshold)
        worker = PipelineWorker(
            db,
            hub,
            pipeline.decide_batch,
            cfg.ingest_batch_size,
            cfg.ingest_batch_wait_ms / 1000,
            cfg.decide_concurrency,
        )
        tasks = [asyncio.create_task(worker.run(), name="pipeline-worker")]
        if llm is not None:
            tasks.append(asyncio.create_task(llm.run(), name="llm-batcher"))
        app.state.settings = cfg
        app.state.llm = llm
        app.state.db = db
        app.state.http = http
        app.state.hub = hub
        app.state.worker = worker
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
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

    @app.get("/stats")
    async def stats() -> dict[str, object]:
        llm = app.state.llm
        return {
            "reports_decided": app.state.worker.processed,
            "llm": llm.stats.as_dict() if llm is not None else None,
            "llm_chain": [s.provider.name for s in llm.chain.slots] if llm is not None else [],
        }

    app.include_router(reports.router)
    app.include_router(ws.router)
    return app
