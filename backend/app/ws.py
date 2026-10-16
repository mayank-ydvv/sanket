"""WebSocket hub, the coalescing broadcaster, and the ``/ws`` endpoint."""

import asyncio
import json
import logging
from collections import OrderedDict
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)

SEND_TIMEOUT_S = 2.0


class Hub:
    """Tracks connected dashboards and fans events out to all of them."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def broadcast(self, event: str, data: Any) -> None:
        """Send one event to every client concurrently. O(c) for c clients.

        The payload is serialised once. Clients that error or stall past
        ``SEND_TIMEOUT_S`` are dropped so one slow tab cannot stall the pipeline.
        """
        if not self._clients:
            return
        message = json.dumps({"type": event, "data": data}, ensure_ascii=False)
        clients = list(self._clients)
        results = await asyncio.gather(
            *(asyncio.wait_for(c.send_text(message), SEND_TIMEOUT_S) for c in clients),
            return_exceptions=True,
        )
        for client, result in zip(clients, results, strict=True):
            if isinstance(result, BaseException):
                log.info("dropping websocket client: %r", result)
                self.disconnect(client)


Key = tuple[str, str]


class Broadcaster:
    """Coalescing, throttled front end to the hub.

    ``publish`` is O(1): it only records the latest state per (entity, id), so a
    surge of updates to one incident collapses into one. ``flush`` runs at most
    once per ``interval_s`` and sends a single ``batch`` message in which
    ``*.updated`` events carry only the fields that changed since the last send.
    With the default 100 ms interval clients receive at most 10 messages/s.
    """

    def __init__(self, hub: Hub, interval_s: float = 0.1, cache_size: int = 20_000) -> None:
        self._hub = hub
        self._interval_s = interval_s
        self._cache_size = cache_size
        self._pending: dict[Key, tuple[str, dict[str, Any]]] = {}
        self._last_sent: OrderedDict[Key, dict[str, Any]] = OrderedDict()
        self.published = 0
        self.flushes = 0

    def publish(self, event: str, data: dict[str, Any]) -> None:
        entity = event.partition(".")[0]
        key = (entity, str(data.get("id", "")))
        self.published += 1
        previous = self._pending.get(key)
        if previous is None:
            self._pending[key] = (event, data)
            return
        prev_event, prev_data = previous
        kept_event = prev_event if prev_event.endswith(".created") else event
        self._pending[key] = (kept_event, {**prev_data, **data})

    async def flush(self) -> int:
        """Send everything pending as one message. O(p) for p pending entities."""
        if not self._pending:
            return 0
        pending, self._pending = self._pending, {}
        events: list[dict[str, Any]] = []
        for key, (event, data) in pending.items():
            last = self._last_sent.get(key)
            if event.endswith(".updated") and last is not None:
                changed = {k: v for k, v in data.items() if last.get(k) != v}
                payload = {"id": key[1], **changed} if changed else None
            else:
                payload = data
            self._last_sent[key] = {**(last or {}), **data}
            self._last_sent.move_to_end(key)
            if payload is not None:
                events.append({"type": event, "data": payload})
        while len(self._last_sent) > self._cache_size:
            self._last_sent.popitem(last=False)
        if events:
            await self._hub.broadcast("batch", events)
            self.flushes += 1
        return len(events)

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self._interval_s)
            try:
                await self.flush()
            except Exception:
                log.exception("broadcast flush failed")


router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    hub: Hub = ws.app.state.hub
    await hub.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(ws)
