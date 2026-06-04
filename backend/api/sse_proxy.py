"""SSE proxy — stream the internal EventBus to the browser.

``event_stream(bus)`` returns an async generator that:
- Subscribes to the EventBus **immediately on construction** (before the first
  ``__anext__`` call), so no events published after the call are missed even if
  the consumer hasn't started iterating yet.
- Yields each event as a standard SSE ``data:`` line.
- Emits a SSE comment keepalive (``": keepalive\\n\\n"``) when no events arrive
  within *keepalive_interval* seconds so proxies and load-balancers do not close
  the connection on inactivity.
- Cleans up the subscription on any exit path (normal, GeneratorExit, or
  CancelledError).

Wire format per SSE spec (RFC):
    data: <json>\\n\\n          — real event
    : keepalive\\n\\n            — SSE comment (ignored by browser EventSource)

``GET /events`` in router.py wraps the returned object in a FastAPI
StreamingResponse with ``media_type="text/event-stream"``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

from backend.core.event_bus import EventBus

# Default keepalive interval in seconds.  15 s is long enough that most CDN /
# proxy idle-timeout defaults (60 s) are not triggered.
_DEFAULT_KEEPALIVE_INTERVAL: float = 15.0


def event_stream(
    bus: EventBus,
    *,
    keepalive_interval: float = _DEFAULT_KEEPALIVE_INTERVAL,
) -> AsyncGenerator[str, None]:
    """Return an async generator that drains *bus* events to the browser as SSE chunks.

    The subscription is registered **synchronously** when this function is called
    so that events published before the first ``async for`` iteration are not lost.

    Args:
        bus: The application EventBus (from ``app.state.bus``).
        keepalive_interval: Seconds of silence before a SSE comment is emitted.
            Exposed as a parameter so tests can pass a small value without
            slowing the suite.

    Returns:
        An async generator that yields SSE-formatted strings — either
        ``"data: <json>\\n\\n"`` for real events or ``": keepalive\\n\\n"`` for
        keepalive comments.
    """
    subscription = bus.subscribe()
    return _generate(subscription, bus, keepalive_interval)


async def _generate(
    subscription,
    bus: EventBus,
    keepalive_interval: float,
) -> AsyncGenerator[str, None]:
    """Inner async generator; separated so the subscription is registered in ``event_stream``."""
    try:
        while True:
            try:
                envelope: dict = await asyncio.wait_for(
                    subscription.__anext__(),  # type: ignore[attr-defined]
                    timeout=keepalive_interval,
                )
                yield f"data: {json.dumps(envelope)}\n\n"
            except asyncio.TimeoutError:
                # No event arrived in time — emit a keepalive SSE comment.
                yield ": keepalive\n\n"
    except (GeneratorExit, asyncio.CancelledError):
        # Client disconnected or the coroutine was cancelled — clean up.
        pass
    finally:
        # Always unregister the subscription queue from the bus, regardless of
        # how the generator exits (normal, disconnect, cancel).
        bus._unregister(subscription._queue)  # type: ignore[attr-defined]
