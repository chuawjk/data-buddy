"""Unit tests for sse_proxy.py — browser-facing SSE stream.

TDD: written before the implementation.

Acceptance criteria (N1-S10):
- Given a connecting SPA, when it subscribes to GET /events, then it receives all bus events
  as SSE with contract-shaped payloads.
- Given an active turn, when events flow, then both domain and activity events reach the SPA.
- Given an idle period, when it elapses, then the connection survives via heartbeat/keepalive.
- Given a client disconnect, when it happens, then the subscription is cleaned up.

Tests use the real EventBus (no mocking of the bus) per story instruction.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from backend.api.sse_proxy import event_stream
from backend.core.event_bus import EventBus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _collect_n(gen, n: int, timeout: float = 2.0) -> list[str]:
    """Collect exactly *n* items from an async generator, with a timeout."""
    results: list[str] = []

    async def _run():
        async for chunk in gen:
            results.append(chunk)
            if len(results) >= n:
                break

    await asyncio.wait_for(_run(), timeout=timeout)
    return results


# ---------------------------------------------------------------------------
# test_event_forwarded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_forwarded():
    """A single published event is forwarded as a correctly formatted SSE line.

    The SSE wire format is: ``data: <json>\\n\\n``.
    The JSON payload must include the ``type`` key and all event fields.
    """
    bus = EventBus()

    # Start the generator before publishing so subscription is registered.
    gen = event_stream(bus)

    # Give the generator a chance to set up its subscription.
    await asyncio.sleep(0)

    # Publish one event.
    await bus.publish("stage.changed", {"stage": "profiling", "ts": 1000000})

    chunks = await _collect_n(gen, 1)

    assert len(chunks) == 1
    line = chunks[0]

    # Must start with "data: " and end with "\n\n"
    assert line.startswith("data: ")
    assert line.endswith("\n\n")

    # The JSON payload must be valid and contain the expected fields.
    payload = json.loads(line[len("data: ") : -2])
    assert payload["type"] == "stage.changed"
    assert payload["stage"] == "profiling"
    assert payload["ts"] == 1000000


# ---------------------------------------------------------------------------
# test_multiple_events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_events():
    """Three events published in order all arrive in order as SSE lines.

    Verifies fan-out ordering and that each event is independently serialised.
    """
    bus = EventBus()
    gen = event_stream(bus)
    await asyncio.sleep(0)

    events = [
        ("stage.changed", {"stage": "profiling", "ts": 1}),
        ("tool.bash_running", {"command": "ls", "ts": 2}),
        ("heartbeat", {"ts": 3}),
    ]
    for event_type, payload in events:
        await bus.publish(event_type, payload)

    chunks = await _collect_n(gen, 3)

    assert len(chunks) == 3
    for i, chunk in enumerate(chunks):
        assert chunk.startswith("data: ")
        assert chunk.endswith("\n\n")
        payload = json.loads(chunk[len("data: ") : -2])
        assert payload["type"] == events[i][0]
        assert payload["ts"] == events[i][1]["ts"]


# ---------------------------------------------------------------------------
# test_disconnect_cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disconnect_cleanup():
    """Closing the generator (simulating client disconnect) unregisters the subscription.

    After aclose(), the bus must have zero subscribers for this connection.
    The bus internal queue list should shrink back to its pre-subscription size.
    """
    bus = EventBus()

    # No subscribers before we start.
    assert len(bus._queues) == 0

    gen = event_stream(bus)

    # Advance the generator so it registers its subscription.
    # We publish one event and consume it to ensure the subscription is active.
    await asyncio.sleep(0)
    await bus.publish("heartbeat", {"ts": 999})
    chunks = await _collect_n(gen, 1)
    assert len(chunks) == 1

    # Subscription should be registered.
    assert len(bus._queues) == 1

    # Simulate client disconnect by closing the generator.
    await gen.aclose()

    # After close, the subscription must be cleaned up.
    assert len(bus._queues) == 0


# ---------------------------------------------------------------------------
# test_keepalive_comment_on_silence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_keepalive_comment_on_silence():
    """After a configurable idle period, event_stream yields a SSE keepalive comment.

    The keepalive format is ``: keepalive\\n\\n`` (SSE comment).
    We pass a very short keepalive_interval to avoid slowing the test suite.
    """
    bus = EventBus()

    # Use a tiny keepalive interval (50 ms) to make the test fast.
    gen = event_stream(bus, keepalive_interval=0.05)

    # Collect one chunk — should be a keepalive comment since no events are published.
    chunks = await _collect_n(gen, 1, timeout=2.0)
    assert len(chunks) == 1

    # SSE comment syntax: lines starting with ":"
    assert chunks[0] == ": keepalive\n\n"
