"""Fan-out from the flight threads to whatever is watching.

The session, the guards and the telemetry stream all run on their own threads;
the WebSocket clients live on the asyncio loop. This is the one crossing point,
and it is deliberately lossy for telemetry: a client that cannot keep up misses
frames rather than slowing the drone down.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)

QUEUE_LIMIT = 200          # ~20 s of telemetry at 10 Hz


class EventHub:
    def __init__(self) -> None:
        self._clients: set[asyncio.Queue[dict[str, Any]]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=QUEUE_LIMIT)
        self._clients.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._clients.discard(queue)

    def publish(self, kind: str, payload: dict[str, Any]) -> None:
        """Safe to call from any thread, including cflib's callback thread."""
        loop = self._loop
        if loop is None or not self._clients:
            return
        message = {"type": kind, **payload}
        try:
            loop.call_soon_threadsafe(self._deliver, message)
        except RuntimeError:
            log.debug("event loop is gone; dropping %s event", kind)

    def _deliver(self, message: dict[str, Any]) -> None:
        for queue in list(self._clients):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # A slow client falls behind rather than blocking a flight.
                try:
                    queue.get_nowait()
                    queue.put_nowait(message)
                except Exception:
                    pass
