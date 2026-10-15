"""WebSocket broadcast hub and the ``/ws`` endpoint."""

import asyncio
import json
import logging
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
