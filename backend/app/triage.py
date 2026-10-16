"""The two pipeline stages the worker runs: place (concurrent) and commit (single writer)."""

import asyncio
from collections.abc import Sequence

from app.cluster.embed import Embedder, embedding_text
from app.cluster.geocode import Geocoder
from app.cluster.location import extract_location
from app.cluster.service import IncidentService, Placed
from app.decision.pipeline import DecisionPipeline
from app.models import Report
from app.ws import Hub


class Triage:
    def __init__(
        self,
        pipeline: DecisionPipeline,
        geocoder: Geocoder,
        embedder: Embedder,
        incidents: IncidentService,
        hub: Hub,
    ) -> None:
        self._pipeline = pipeline
        self._geocoder = geocoder
        self._embedder = embedder
        self._incidents = incidents
        self._hub = hub

    async def place(self, reports: Sequence[Report]) -> list[Placed]:
        """Decide, locate and embed one batch. Safe to run for many batches at once.

        O(b·L) decisions, one embedding pass per batch in a worker thread, and
        geocoding that is cache-first with at most one rate-limited network call each.
        """
        results = await self._pipeline.decide_batch(reports)
        mentions = [
            res.decision.location_text or extract_location(rep.raw_text)
            for rep, res in zip(reports, results, strict=True)
        ]
        points = await asyncio.gather(*(self._geocoder.geocode(m) for m in mentions))
        texts = [embedding_text(rep.raw_text, res.decision) for rep, res in zip(reports, results, strict=True)]
        vectors = await asyncio.to_thread(self._embedder.encode, texts)
        return [
            Placed(report, result, vectors[i], mentions[i], points[i])
            for i, (report, result) in enumerate(zip(reports, results, strict=True))
        ]

    async def commit(self, items: Sequence[Placed]) -> int:
        """Cluster + persist one batch, then broadcast what changed. Single caller only."""
        outcome = await self._incidents.assign(items)
        for incident in outcome.created:
            await self._hub.broadcast("incident.created", incident.model_dump(mode="json"))
        for incident in outcome.updated:
            await self._hub.broadcast("incident.updated", incident.model_dump(mode="json"))
        for report in outcome.reports:
            await self._hub.broadcast("report.created", report.model_dump(mode="json"))
        return len(outcome.reports)
