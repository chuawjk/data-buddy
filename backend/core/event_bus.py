"""In-process async pub/sub event bus.

Publishers call ``bus.publish(event_type, payload)`` to broadcast an event.
Subscribers call ``bus.subscribe()`` to obtain an async iterator that yields every
event published after the call returns.  Each subscriber gets an independent
asyncio.Queue so slow consumers do not block each other or the publisher.

Design notes:
- One ``asyncio.Queue`` per active subscriber (fan-out by copying the payload).
- The event dict delivered to subscribers has the ``event_type`` merged in under
  the key ``"type"`` for convenience — callers never have to do it themselves.
- Thread-safety is intentionally out of scope: everything runs in a single
  asyncio event loop (FastAPI's default).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any


class EventBus:
    """Simple async fan-out pub/sub bus backed by per-subscriber queues."""

    def __init__(self) -> None:
        self._queues: list[asyncio.Queue[dict[str, Any]]] = []

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        """Broadcast an event to all active subscribers.

        The ``event_type`` is merged into the payload dict under the key
        ``"type"``.  Each subscriber receives an independent copy so mutations
        in one consumer cannot affect others.

        Args:
            event_type: The event type string (e.g. ``"stage.changed"``).
            payload: Arbitrary JSON-serialisable dict of event data.
        """
        envelope: dict[str, Any] = {"type": event_type, **payload}
        for queue in list(self._queues):
            await queue.put(envelope)

    def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        """Return an async iterator that yields events as they are published.

        The subscription is active from the moment this method is called.
        Events published *before* this call are not delivered (no replay).
        The subscription is automatically removed when the iterator is garbage-
        collected or when the consuming coroutine exits the ``async for`` loop.

        Yields:
            Event dicts with a ``"type"`` key plus whatever fields were in the
            original payload.
        """
        return _Subscription(self)

    # ------------------------------------------------------------------
    # Internal helpers used by _Subscription
    # ------------------------------------------------------------------

    def _register(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._queues.append(queue)

    def _unregister(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        try:
            self._queues.remove(queue)
        except ValueError:
            pass  # already removed — idempotent


class _Subscription:
    """Async iterator returned by :meth:`EventBus.subscribe`.

    Manages the lifecycle of a single subscriber queue.
    """

    __slots__ = ("_bus", "_queue")

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        bus._register(self._queue)

    def __aiter__(self) -> "_Subscription":
        return self

    async def __anext__(self) -> dict[str, Any]:
        return await self._queue.get()

    def __del__(self) -> None:
        self._bus._unregister(self._queue)
