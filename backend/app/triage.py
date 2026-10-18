"""Pipeline stages: place (concurrent) -> commit (single writer) -> revise (background LLM).

A report reaches the board as soon as the local model and rules have decided it.
If that decision is uncertain, the fast LLM re-checks it in the background and the
report and its incident are revised in place when the answer arrives. Revisions
are started only after the commit, so a revision never races its own report.
"""

import asyncio
import logging
from collections.abc import Sequence

import numpy as np

from app.alerts.service import AlertService
from app.cluster.embed import Embedder, Matrix, embedding_text
from app.cluster.geocode import GeoPoint, Geocoder
from app.cluster.location import extract_location
from app.cluster.service import ChangeSet, IncidentService, Placed, Revision
from app.decision.pipeline import DecisionPipeline
from app.models import DecisionResult, Report
from app.reasoning.scheduler import Reasoner
from app.ws import Broadcaster

log = logging.getLogger(__name__)


class Triage:
    def __init__(
        self,
        pipeline: DecisionPipeline,
        geocoder: Geocoder,
        embedder: Embedder,
        incidents: IncidentService,
        alerts: AlertService,
        broadcaster: Broadcaster,
        reasoner: Reasoner | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._reasoner = reasoner
        self._geocoder = geocoder
        self._embedder = embedder
        self._incidents = incidents
        self._alerts = alerts
        self._broadcaster = broadcaster
        self._revisions: asyncio.Queue[list[Revision]] = asyncio.Queue()
        self._refining: set[asyncio.Task[None]] = set()
        self.revised = 0

    async def _locate_and_embed(
        self, reports: Sequence[Report], results: Sequence[DecisionResult]
    ) -> tuple[list[str | None], list[GeoPoint | None], Matrix]:
        """Location mention, geocode and embedding for each report. One model pass per batch."""
        located = await asyncio.gather(
            *(self._locate(rep.raw_text, res.decision.location_text) for rep, res in zip(reports, results, strict=True))
        )
        mentions = [mention for mention, _ in located]
        points = [point for _, point in located]
        texts = [embedding_text(rep.raw_text, res.decision) for rep, res in zip(reports, results, strict=True)]
        vectors = await asyncio.to_thread(self._embedder.encode, texts)
        return mentions, points, vectors

    async def _locate(self, text: str, stated: str | None) -> tuple[str | None, GeoPoint | None]:
        """Try the model's location first, then the place extracted from the text.

        Model location strings are sometimes not places ("3rd floor", "in the house");
        the text extractor recovers the real place when the model's string fails.
        """
        candidates = list(dict.fromkeys(c for c in (stated, extract_location(text)) if c))
        for candidate in candidates:
            point = await self._geocoder.geocode(candidate)
            if point is not None:
                return candidate, point
        return (candidates[0] if candidates else None), None

    async def place(self, reports: Sequence[Report]) -> list[Placed]:
        """Stage 1: fast decision, location and embedding. Runs for many batches at once. O(b·L)."""
        results = await self._pipeline.decide_fast(reports)
        mentions, points, vectors = await self._locate_and_embed(reports, results)
        return [
            Placed(report, result, vectors[i], mentions[i], points[i], self._pipeline.wants_llm(result))
            for i, (report, result) in enumerate(zip(reports, results, strict=True))
        ]

    async def commit(self, items: Sequence[Placed]) -> int:
        """Stage 2 (single caller): cluster + persist, publish, then start LLM revisions."""
        changes = await self._incidents.assign(items)
        self._publish(changes, report_event="report.created")
        refine = [item for item in items if item.refining]
        if refine:
            task = asyncio.create_task(self._refine(refine))
            self._refining.add(task)
            task.add_done_callback(self._refining.discard)
        await self._auto_dispatch(changes)
        return len(changes.reports)

    async def _refine(self, items: Sequence[Placed]) -> None:
        try:
            reports = [item.report for item in items]
            revised = await self._pipeline.refine(reports, [item.result for item in items])
            mentions, points, vectors = await self._locate_and_embed(reports, revised)
            self._revisions.put_nowait(
                [
                    Revision(report.id, result, np.asarray(vectors[i]), mentions[i], points[i])
                    for i, (report, result) in enumerate(zip(reports, revised, strict=True))
                ]
            )
        except Exception:
            log.exception("LLM refinement failed for %d reports", len(items))

    async def run_revisions(self) -> None:
        """Apply LLM revisions one batch at a time (the incident service serialises writes)."""
        while True:
            revisions = await self._revisions.get()
            try:
                changes = await self._incidents.revise(revisions)
                self.revised += len(changes.reports)
                self._publish(changes, report_event="report.updated")
                await self._auto_dispatch(changes)
            except Exception:
                log.exception("applying %d revisions failed", len(revisions))

    def _publish(self, changes: ChangeSet, report_event: str) -> None:
        if self._reasoner is not None:
            self._reasoner.consider([*changes.created, *changes.updated])
        for incident in changes.created:
            self._broadcaster.publish("incident.created", incident.model_dump(mode="json"))
        for incident in changes.updated:
            self._broadcaster.publish("incident.updated", incident.model_dump(mode="json"))
        for report in changes.reports:
            self._broadcaster.publish(report_event, report.model_dump(mode="json"))

    async def _auto_dispatch(self, changes: ChangeSet) -> None:
        """Alert immediately for incidents whose evidence clears the auto-dispatch gate."""
        for incident in [*changes.created, *changes.updated]:
            if incident.lane == "auto" and incident.status == "open":
                await self._alerts.dispatch(incident.id, triggered_by="auto")
            elif incident.status == "dispatched":
                await self._alerts.reroute_if_department_changed(incident)
