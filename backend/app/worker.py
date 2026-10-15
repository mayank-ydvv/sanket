"""Ingest worker: drains the report queue in micro-batches and runs the pipeline."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence

from app.db import Database
from app.models import DecisionResult, Report
from app.ws import Hub

log = logging.getLogger(__name__)

DecideFn = Callable[[Sequence[Report]], Awaitable[list[DecisionResult]]]


class PipelineWorker:
    """Single consumer of the ingest queue, so pipeline state has exactly one writer."""

    def __init__(
        self, db: Database, hub: Hub, decide: DecideFn, batch_size: int, batch_wait_s: float
    ) -> None:
        self._db = db
        self._hub = hub
        self._decide = decide
        self._batch_size = batch_size
        self._batch_wait_s = batch_wait_s
        self._queue: asyncio.Queue[Report] = asyncio.Queue()

    def submit(self, report: Report) -> None:
        """Enqueue a persisted report. O(1)."""
        self._queue.put_nowait(report)

    async def run(self) -> None:
        """Process batches forever. A failing batch is logged and never kills the loop."""
        while True:
            batch = await self._next_batch()
            try:
                await self._process(batch)
            except Exception:
                log.exception("pipeline batch of %d failed", len(batch))

    async def _next_batch(self) -> list[Report]:
        """Wait for one report, then gather more for up to ``batch_wait_s``. O(b)."""
        batch = [await self._queue.get()]
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._batch_wait_s
        while len(batch) < self._batch_size:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                batch.append(await asyncio.wait_for(self._queue.get(), remaining))
            except TimeoutError:
                break
        return batch

    async def _process(self, batch: Sequence[Report]) -> None:
        """Decide, persist and broadcast one batch. O(b) plus the decide cost."""
        results = await self._decide(batch)
        await self._db.save_decisions(
            [(report.id, result) for report, result in zip(batch, results, strict=True)]
        )
        for report, result in zip(batch, results, strict=True):
            decided = report.model_copy(
                update={
                    "decision": result.decision,
                    "confidence": result.confidence,
                    "source": result.source,
                }
            )
            await self._hub.broadcast("report.created", decided.model_dump(mode="json"))
