"""Unit tests for EventBus — in-process async pub/sub bus.

TDD: these were written before the implementation.
Acceptance criterion: when a component publishes an event, every active subscriber receives it.
"""

import asyncio

import pytest

from backend.core.event_bus import EventBus


@pytest.mark.asyncio
async def test_single_subscriber_receives_published_event():
    """A subscriber receives an event published after it subscribes."""
    bus = EventBus()
    events = []

    async def collect():
        async for evt in bus.subscribe():
            events.append(evt)
            break  # take exactly one event then stop

    task = asyncio.create_task(collect())
    # Yield control so the subscriber coroutine starts and is waiting.
    await asyncio.sleep(0)

    await bus.publish("stage.changed", {"stage": "profiling"})

    await asyncio.wait_for(task, timeout=2.0)
    assert len(events) == 1
    assert events[0] == {"type": "stage.changed", "stage": "profiling"}


@pytest.mark.asyncio
async def test_two_subscribers_both_receive_event():
    """Multiple concurrent subscribers each receive every published event (fan-out)."""
    bus = EventBus()
    received_a: list[dict] = []
    received_b: list[dict] = []

    async def collect_a():
        async for evt in bus.subscribe():
            received_a.append(evt)
            break

    async def collect_b():
        async for evt in bus.subscribe():
            received_b.append(evt)
            break

    task_a = asyncio.create_task(collect_a())
    task_b = asyncio.create_task(collect_b())
    # Let both coroutines advance to the point where they await a queue item.
    await asyncio.sleep(0)

    await bus.publish("profile.ready", {"profile": {"shape": {"rows": 100, "columns": 5}}})

    await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=2.0)

    assert len(received_a) == 1
    assert len(received_b) == 1
    # Both received the same event payload (independent copies).
    assert received_a[0]["type"] == "profile.ready"
    assert received_b[0]["type"] == "profile.ready"


@pytest.mark.asyncio
async def test_publish_with_no_subscribers_does_not_error():
    """Publishing when no subscribers are active must not raise."""
    bus = EventBus()
    # Should complete without raising.
    await bus.publish("heartbeat", {"ts": 1234567890})


@pytest.mark.asyncio
async def test_subscriber_receives_events_in_order():
    """Events published sequentially arrive in order for a subscriber."""
    bus = EventBus()
    received: list[dict] = []

    async def collect():
        async for evt in bus.subscribe():
            received.append(evt)
            if len(received) == 3:
                break

    task = asyncio.create_task(collect())
    await asyncio.sleep(0)

    for i in range(3):
        await bus.publish("heartbeat", {"seq": i})

    await asyncio.wait_for(task, timeout=2.0)

    assert [e["seq"] for e in received] == [0, 1, 2]


@pytest.mark.asyncio
async def test_late_subscriber_does_not_receive_prior_events():
    """A subscriber registered after a publish does not receive the earlier event."""
    bus = EventBus()

    # Publish before any subscriber exists.
    await bus.publish("stage.changed", {"stage": "profiling"})

    received: list[dict] = []

    async def collect():
        async for evt in bus.subscribe():
            received.append(evt)
            break

    task = asyncio.create_task(collect())
    await asyncio.sleep(0)

    # Publish a second event that the late subscriber SHOULD receive.
    await bus.publish("stage.changed", {"stage": "planning"})

    await asyncio.wait_for(task, timeout=2.0)

    # Only the second event (planning) should be present.
    assert len(received) == 1
    assert received[0]["stage"] == "planning"
