"""FastAPI application factory. Run with ``uvicorn app.main:create_app --factory``."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import auth_api, benchmark_api, incidents_api, simulate_api, ws
from app.auth import LoginThrottle
from app.cost import CostMeter
from app.simulate import SimulationRunner
from app.alerts.senders import AlertSender, MockSender, TwilioSmsSender
from app.alerts.service import AlertService
from app.cluster.embed import Embedder, HashingEmbedder, SentenceEmbedder
from app.cluster.geocode import Geocoder, GeocoderConfig
from app.cluster.index import IncidentIndex
from app.cluster.service import IncidentService
from app.config import Settings, get_settings
from app.db import Database
from app.decision.factory import build_llm_decider, build_reasoning_chain
from app.decision.llm import FallbackChain, LLMDecider, LLMStats
from app.demo import DemoCache, DemoRecorder, ReplayDecider
from app.decision.providers import RateLimiter
from app.reasoning.scheduler import Reasoner, ReasonerConfig
from app.decision.local import LocalClassifier
from app.decision.pipeline import DecisionPipeline
from app.decision.rules import PrankTracker, SafetyRules
from app.intake import reports, twilio
from app.intake.service import Intake
from app.stt.transcribe import GroqWhisper, SarvamSTT, SpeechToText, STTChain
from app.triage import Triage
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


async def load_embedder(settings: Settings) -> Embedder:
    """Multilingual sentence model, or the lexical hashing fallback if it cannot load."""
    if settings.embedding_backend == "sentence":
        try:
            embedder = await asyncio.to_thread(SentenceEmbedder, settings.embedding_model)
        except Exception:
            log.exception("embedding model failed to load; falling back to hashed n-grams")
        else:
            log.info("loaded embedding model %s", settings.embedding_model)
            return embedder
    return HashingEmbedder()


def build_sender(settings: Settings, http: httpx.AsyncClient) -> AlertSender:
    if settings.mock_alerts:
        return MockSender()
    if settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_from_number:
        return TwilioSmsSender(http, settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_from_number)
    log.error("MOCK_ALERTS=false but Twilio credentials are missing; using the mock sender")
    return MockSender()


def build_stt(settings: Settings, http: httpx.AsyncClient) -> STTChain:
    providers: list[SpeechToText] = []
    if settings.groq_api_key:
        providers.append(GroqWhisper(http, settings.groq_api_key, settings.groq_stt_model))
    if settings.sarvam_api_key:
        providers.append(SarvamSTT(http, settings.sarvam_api_key, settings.sarvam_stt_model))
    return STTChain(providers)


def create_app(settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    """Build the app. Tests pass their own settings and, optionally, a mock HTTP transport."""
    cfg = settings or get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = await Database.open(cfg.db_path)
        http = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0), transport=transport)
        hub = ws.Hub()
        broadcaster = ws.Broadcaster(hub)
        limiters: dict[str, RateLimiter] = {}  # one quota per provider/model, shared by both systems
        recorder = DemoRecorder(cfg.demo_run_path) if cfg.demo_record and not cfg.demo_cache else None
        replay = DemoCache.load(cfg.demo_run_path) if cfg.demo_cache else None
        llm: LLMDecider | ReplayDecider | None
        if replay is not None:
            llm = ReplayDecider(replay)
            log.warning("DEMO_CACHE=true: replaying recorded LLM answers from %s, no provider calls", cfg.demo_run_path)
        else:
            llm = build_llm_decider(cfg, http, limiters, recorder)
        if recorder is not None:
            log.warning("DEMO_RECORD=true: appending LLM answers to %s", recorder.path)
        if llm is None:
            log.warning("no LLM provider configured; uncertain reports keep their local decision")
        else:
            log.info("LLM chain: %s", " -> ".join(s.provider.name for s in llm.chain.slots))
        rules = SafetyRules(PrankTracker(cfg.prank_window_s, cfg.prank_min_reports))
        pipeline = DecisionPipeline(await load_local_classifier(cfg), llm, rules, cfg.conf_threshold)
        geocoder = Geocoder(
            http,
            db,
            GeocoderConfig(
                url=cfg.nominatim_url,
                user_agent=cfg.nominatim_user_agent,
                district=cfg.geo_district,
                viewbox=cfg.geo_viewbox,
                max_wait_s=cfg.geocode_max_wait_s,
                network=cfg.geocode_network and replay is None,
            ),
        )
        index = IncidentIndex(
            center_lat=cfg.geo_center[0],
            radius_km=cfg.cluster_radius_km,
            window_s=cfg.cluster_window_s,
            similarity=cfg.cluster_similarity,
            department_bonus=cfg.cluster_department_bonus,
            unlocated_k=cfg.cluster_unlocated_candidates,
        )
        incidents = IncidentService(db, index)
        log.info("restored %d open incidents into the clustering index", await incidents.restore())
        alerts = AlertService(
            db, incidents, broadcaster, build_sender(cfg, http), cfg.alert_contacts, cfg.alert_ack_timeout_s
        )
        log.info("resumed %d alert escalation timers", await alerts.restore())
        reasoning_chain: FallbackChain | None = None
        if cfg.reasoning_enabled:
            reasoning_chain = (
                FallbackChain([], LLMStats(), 0.0) if replay is not None else build_reasoning_chain(cfg, http, limiters)
            )
        reasoner = (
            Reasoner(
                incidents,
                db,
                reasoning_chain,
                broadcaster,
                ReasonerConfig(
                    debounce_s=cfg.reasoning_debounce_s,
                    min_reports=cfg.reasoning_min_reports,
                    min_severity=cfg.reasoning_min_severity,
                    neighbor_m=cfg.reasoning_neighbor_m,
                    neighbor_window_s=cfg.reasoning_neighbor_window_s,
                    max_reports=cfg.reasoning_max_reports,
                    concurrency=cfg.reasoning_concurrency,
                ),
                recorder=recorder,
                replay=replay,
            )
            if reasoning_chain is not None
            else None
        )
        triage = Triage(pipeline, geocoder, await load_embedder(cfg), incidents, alerts, broadcaster, reasoner)
        worker = PipelineWorker(
            triage.place,
            triage.commit,
            cfg.ingest_batch_size,
            cfg.ingest_batch_wait_ms / 1000,
            cfg.decide_concurrency,
        )
        tasks = [
            asyncio.create_task(worker.run(), name="pipeline-worker"),
            asyncio.create_task(triage.run_revisions(), name="llm-revisions"),
            asyncio.create_task(broadcaster.run(), name="broadcaster"),
            asyncio.create_task(alerts.run(), name="alert-escalation"),
        ]
        if reasoner is not None:
            tasks.append(asyncio.create_task(reasoner.run(), name="reasoning"))
        if llm is not None:
            tasks.append(asyncio.create_task(llm.run(), name="llm-batcher"))
        app.state.settings = cfg
        app.state.mode = "demo-replay" if replay is not None else ("recording" if recorder is not None else "live")
        app.state.llm = llm
        app.state.reasoner = reasoner
        app.state.db = db
        app.state.http = http
        app.state.hub = hub
        app.state.worker = worker
        app.state.incidents = incidents
        app.state.geocoder = geocoder
        app.state.broadcaster = broadcaster
        app.state.alerts = alerts
        app.state.triage = triage
        intake = Intake(db, worker, cfg.caller_salt)
        app.state.intake = intake
        app.state.login_throttle = LoginThrottle()
        app.state.simulation = SimulationRunner(intake, broadcaster, lambda: worker.processed)
        cost = CostMeter(
            [c.stats for c in (llm.chain if llm else None, reasoning_chain) if c is not None],
            cfg.llm_prices,
            cfg.counterfactual_price,
            (cfg.counterfactual_input_tokens, cfg.counterfactual_output_tokens),
            cfg.usd_to_inr,
            lambda: worker.processed,
            broadcaster,
        )
        app.state.cost = cost
        tasks.append(asyncio.create_task(cost.run(), name="cost-meter"))
        app.state.stt = build_stt(cfg, http)
        app.state.voice_tasks = set()
        try:
            yield
        finally:
            app.state.simulation.cancel()
            for task in [*tasks, *app.state.voice_tasks]:
                task.cancel()
            for task in [*tasks, *app.state.voice_tasks]:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await http.aclose()
            await db.close()
            if recorder is not None:
                recorder.close()

    app = FastAPI(title="Sanket", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "mode": getattr(app.state, "mode", "starting")}

    @app.get("/stats", dependencies=[auth_api.require_user])
    async def stats() -> dict[str, object]:
        llm = app.state.llm
        return {
            "mode": app.state.mode,
            "reports_decided": app.state.worker.processed,
            "reports_revised": app.state.triage.revised,
            "broadcast": {"published": app.state.broadcaster.published, "flushes": app.state.broadcaster.flushes},
            "llm": llm.stats.as_dict() if llm is not None else None,
            "llm_chain": [s.provider.name for s in llm.chain.slots] if llm is not None else [],
            "geocoder_network_calls": app.state.geocoder.network_calls,
            "reasoning": (
                {**app.state.reasoner.stats.__dict__, "chain": [s.provider.name + "/" + s.provider.model for s in app.state.reasoner.chain.slots]}
                if app.state.reasoner is not None
                else None
            ),
            "cost": app.state.cost.snapshot().model_dump(),
        }

    protected = [auth_api.require_user]
    app.include_router(auth_api.router)
    app.include_router(reports.router)  # POST /reports is public citizen intake; GET needs login
    app.include_router(twilio.router)  # authenticated by Twilio signature instead
    app.include_router(simulate_api.router, dependencies=protected)
    app.include_router(benchmark_api.router, dependencies=protected)
    app.include_router(incidents_api.router, dependencies=protected)
    app.include_router(incidents_api.alerts_router, dependencies=protected)
    app.include_router(ws.router)
    return app
