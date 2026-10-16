"""Single entry point for every channel: persist the raw report, then queue it."""

import time
import uuid

from app.db import Database
from app.models import Channel, Report
from app.privacy import hash_caller
from app.worker import PipelineWorker


class Intake:
    def __init__(self, db: Database, worker: PipelineWorker[object], caller_salt: str) -> None:
        self._db = db
        self._worker = worker
        self._salt = caller_salt

    async def submit(
        self, text: str, channel: Channel, caller: str | None, language: str | None = None
    ) -> Report:
        """O(L): hash the caller, store the report, enqueue it for triage."""
        report = Report(
            id=f"r_{uuid.uuid4().hex}",
            channel=channel,
            caller_hash=hash_caller(caller, self._salt),
            raw_text=text.strip(),
            language=language,
            received_at=time.time(),
        )
        async with self._db.transaction():
            await self._db.insert_report(report)
        self._worker.submit(report)
        return report
