"""Ingest worker: two stages connected by a queue.

Stage 1 (concurrent, bounded): micro-batches from the ingest queue are decided in
parallel, so a batch waiting on the LLM never blocks the next batch's local pass.
Stage 2 (single consumer): persists decisions, writes the audit trail and
broadcasts. Being the only writer of downstream state, it needs no locks.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence

from app.db import Database
from app.models import DecisionResult, Report
from app.ws import Hub

log = logging.getLogger(__name__)

DecideFn = Callable[[Sequence[Report]], Awaitable[list[DecisionResult]]]
Decided = list[tuple[Report, DecisionResult]]


class PipelineWorker:
    def __init__(
        self,
        db: Database,
        hub: Hub,
        decide: DecideFn,
        batch_size: int,
        batch_wait_s: float,
        concurrency: int = 8,
    ) -> None:
        self._db = db
        self._hub = hub
        self._decide = decide
        self._batch_size = batch_size
        self._batch_wait_s = batch_wait_s
        self._slots = asyncio.Semaphore(concurrency)
        self._ingest: asyncio.Queue[Report] = asyncio.Queue()
        self._decided: asyncio.Queue[Decided] = asyncio.Queue()
        self._tasks: set[asyncio.Task[None]] = set()
        self.processed = 0

    def submit(self, report: Report) -> None:
        """Enqueue a persisted report. O(1)."""
        self._ingest.put_nowait(report)

    async def run(self) -> None:
        """Run both stages until cancelled."""
        sink = asyncio.create_task(self._sink(), name="pipeline-sink")
        try:
            while True:
                batch = await self._next_batch()
                await self._slots.acquire()
                task = asyncio.create_task(self._decide_batch(batch))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
        finally:
            sink.cancel()
            for task in self._tasks:
                task.cancel()

    async def _next_batch(self) -> list[Report]:
        """Wait for one report, then gather more for up to ``batch_wait_s``. O(b)."""
        batch = [await self._ingest.get()]
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._batch_wait_s
        while len(batch) < self._batch_size:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                batch.append(await asyncio.wait_for(self._ingest.get(), remaining))
            except TimeoutError:
                break
        return batch

    async def _decide_batch(self, batch: list[Report]) -> None:
        try:
            results = await self._decide(batch)
            self._decided.put_nowait(list(zip(batch, results, strict=True)))
        except Exception:
            log.exception("deciding a batch of %d failed", len(batch))
        finally:
            self._slots.release()

    async def _sink(self) -> None:
        """Single writer: persist + audit + broadcast each decided batch. O(b) per batch."""
        while True:
            items = await self._decided.get()
            try:
                await self._db.save_decisions([(report.id, result) for report, result in items])
                for report, result in items:
                    decided = report.model_copy(
                        update={
                            "decision": result.decision,
                            "confidence": result.confidence,
                            "source": result.source,
                            "flags": result.rules_fired,
                        }
                    )
                    await self._hub.broadcast("report.created", decided.model_dump(mode="json"))
                self.processed += len(items)
            except Exception:
                log.exception("persisting a batch of %d failed", len(items))
