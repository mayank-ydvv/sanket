"""Ingest worker: two stages connected by a queue.

Stage 1 (concurrent, bounded): micro-batches from the ingest queue are decided,
located and embedded in parallel, so a batch waiting on the LLM or geocoder never
blocks the next batch's local pass.
Stage 2 (single consumer): clusters, persists and broadcasts. Being the only
writer of incident state, it needs no further coordination.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Generic, TypeVar

from app.models import Report

log = logging.getLogger(__name__)

T = TypeVar("T")


class PipelineWorker(Generic[T]):
    def __init__(
        self,
        place: Callable[[Sequence[Report]], Awaitable[list[T]]],
        commit: Callable[[Sequence[T]], Awaitable[int]],
        batch_size: int,
        batch_wait_s: float,
        concurrency: int = 8,
    ) -> None:
        self._place = place
        self._commit = commit
        self._batch_size = batch_size
        self._batch_wait_s = batch_wait_s
        self._slots = asyncio.Semaphore(concurrency)
        self._ingest: asyncio.Queue[Report] = asyncio.Queue()
        self._placed: asyncio.Queue[list[T]] = asyncio.Queue()
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
                task = asyncio.create_task(self._stage_one(batch))
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

    async def _stage_one(self, batch: list[Report]) -> None:
        try:
            self._placed.put_nowait(await self._place(batch))
        except Exception:
            log.exception("stage 1 failed for a batch of %d", len(batch))
        finally:
            self._slots.release()

    async def _sink(self) -> None:
        while True:
            items = await self._placed.get()
            try:
                self.processed += await self._commit(items)
            except Exception:
                log.exception("stage 2 failed for a batch of %d", len(items))
