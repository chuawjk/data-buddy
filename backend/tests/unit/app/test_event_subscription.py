"""Unit tests for the persistent OpenCode event subscription (N1-S08).

TDD: tests written before implementation.

Acceptance criteria covered:
- Exactly one subscription task is created at startup.
- Events with a foreign sessionID are dropped (not published to bus).
- Events with the correct sessionID are passed through.
- message.part.delta → message.part (text streaming).
- message.part.updated (tool, bash, running) → tool.bash_running.
- message.part.updated (tool, bash, completed) → tool.bash_done.
- message.part.updated (tool, apply_patch, completed with metadata.files) → tool.file_written.
- server.heartbeat → nothing published to bus (timer reset only).
- 31+ seconds without a server.heartbeat → reconnect (new SSE connection opened).

Mock strategy: the httpx-sse stream is mocked entirely.  No real OpenCode
server is contacted.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from backend.event_bus import EventBus
from backend.opencode_client import OpenCodeClient
from backend.state_manager import StateManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OWN_SESSION = "ses_own_session_id"
_FOREIGN_SESSION = "ses_foreign_session_id"


def _make_state_manager(tmp_path: Path, session_id: str = _OWN_SESSION) -> StateManager:
    sm = StateManager(path=tmp_path / "state.json")
    sm.update(opencode_session_id=session_id)
    return sm


def _make_client(tmp_path: Path, session_id: str = _OWN_SESSION) -> OpenCodeClient:
    sm = _make_state_manager(tmp_path, session_id)
    return OpenCodeClient(state_manager=sm)


def _raw_event(event_type: str, properties: dict[str, Any]) -> MagicMock:
    """Build a mock SSE event as returned by httpx-sse."""
    evt = MagicMock()
    evt.data = json.dumps({"id": "evt_test", "type": event_type, "properties": properties})
    return evt


async def _run_subscription_with_events(
    client: OpenCodeClient,
    bus: EventBus,
    raw_events: list[MagicMock],
    *,
    heartbeat_timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """Drive start_event_subscription with a mocked SSE stream and collect bus output.

    The subscription task runs until the mock event list is exhausted, then we
    cancel the task and collect what the bus published.
    """
    received: list[dict[str, Any]] = []
    sub = bus.subscribe()

    async def _collect() -> None:
        async for event in sub:
            received.append(event)

    def _fake_connect_sse(http_client, method, url, **kwargs):
        """Sync context manager factory that yields a fake SSE source.

        aconnect_sse is an @asynccontextmanager — it is called synchronously
        and returns an async context manager.  The mock must match that shape.
        """

        class FakeSSEResponse:
            async def aiter_sse(self):
                for evt in raw_events:
                    yield evt

        class FakeCtx:
            async def __aenter__(self):
                return FakeSSEResponse()

            async def __aexit__(self, *args):
                pass

        return FakeCtx()

    with (
        patch("backend.opencode_client.aconnect_sse", side_effect=_fake_connect_sse),
        patch("backend.opencode_client.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_http

        task = asyncio.create_task(
            client.start_event_subscription(bus, heartbeat_timeout=heartbeat_timeout)
        )
        collector = asyncio.create_task(_collect())

        # Give the coroutine time to process events then stop it.
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Give the collector a moment to drain any queued items.
        await asyncio.sleep(0.01)
        collector.cancel()
        try:
            await collector
        except asyncio.CancelledError:
            pass

    return received


# ---------------------------------------------------------------------------
# test_single_connection_at_startup
# ---------------------------------------------------------------------------


async def test_single_connection_at_startup(tmp_path: Path) -> None:
    """Only one GET /event connection is opened for the subscription task."""
    client = _make_client(tmp_path)
    bus = EventBus()

    connect_calls: list[Any] = []

    def _fake_connect_sse(http_client, method, url, **kwargs):
        connect_calls.append((method, url))

        class FakeSSEResponse:
            async def aiter_sse(self):
                # Immediately end (no events).
                return
                yield  # makes this a generator  # noqa: E701

        class FakeCtx:
            async def __aenter__(self):
                return FakeSSEResponse()

            async def __aexit__(self, *args):
                pass

        return FakeCtx()

    with (
        patch("backend.opencode_client.aconnect_sse", side_effect=_fake_connect_sse),
        patch("backend.opencode_client.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_http

        task = asyncio.create_task(client.start_event_subscription(bus, heartbeat_timeout=30.0))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # The subscription itself uses one connection (reconnect loop exits when cancelled).
    assert len(connect_calls) == 1
    assert connect_calls[0][0] == "GET"


# ---------------------------------------------------------------------------
# test_session_id_filter_drops_foreign
# ---------------------------------------------------------------------------


async def test_session_id_filter_drops_foreign(tmp_path: Path) -> None:
    """An event with a foreign sessionID is dropped; bus receives nothing."""
    client = _make_client(tmp_path, session_id=_OWN_SESSION)
    bus = EventBus()

    foreign_idle = _raw_event(
        "session.idle",
        {"sessionID": _FOREIGN_SESSION},
    )

    received = await _run_subscription_with_events(client, bus, [foreign_idle])
    assert received == [], f"Expected no events, got: {received}"


# ---------------------------------------------------------------------------
# test_session_id_filter_passes_own
# ---------------------------------------------------------------------------


async def test_session_id_filter_passes_own(tmp_path: Path) -> None:
    """An event with the correct sessionID is passed through and published."""
    client = _make_client(tmp_path, session_id=_OWN_SESSION)
    bus = EventBus()

    own_idle = _raw_event(
        "session.idle",
        {"sessionID": _OWN_SESSION},
    )

    received = await _run_subscription_with_events(client, bus, [own_idle])
    assert any(e["type"] == "session.idle" for e in received), (
        f"Expected session.idle in bus output, got: {received}"
    )


# ---------------------------------------------------------------------------
# test_text_part_normalised
# ---------------------------------------------------------------------------


async def test_text_part_normalised(tmp_path: Path) -> None:
    """message.part.delta with delta → bus gets message.part with content."""
    client = _make_client(tmp_path)
    bus = EventBus()

    raw = _raw_event(
        "message.part.delta",
        {
            "sessionID": _OWN_SESSION,
            "partID": "prt_abc123",
            "delta": "Hello, world!",
            "time": 1000000,
        },
    )

    received = await _run_subscription_with_events(client, bus, [raw])
    assert any(e["type"] == "message.part" for e in received), (
        f"Expected message.part in bus, got: {received}"
    )
    mp_events = [e for e in received if e["type"] == "message.part"]
    assert mp_events[0]["content"] == "Hello, world!"
    assert mp_events[0]["part_id"] == "prt_abc123"


# ---------------------------------------------------------------------------
# test_tool_running_normalised
# ---------------------------------------------------------------------------


async def test_tool_running_normalised(tmp_path: Path) -> None:
    """message.part.updated (bash, running) → bus gets tool.bash_running."""
    client = _make_client(tmp_path)
    bus = EventBus()

    raw = _raw_event(
        "message.part.updated",
        {
            "sessionID": _OWN_SESSION,
            "part": {
                "type": "tool",
                "tool": "bash",
                "state": {
                    "status": "running",
                    "input": {
                        "command": "ls -la",
                        "description": "List files",
                    },
                },
            },
            "time": 1779784977098,
        },
    )

    received = await _run_subscription_with_events(client, bus, [raw])
    assert any(e["type"] == "tool.bash_running" for e in received), (
        f"Expected tool.bash_running in bus, got: {received}"
    )
    events = [e for e in received if e["type"] == "tool.bash_running"]
    assert events[0]["command"] == "ls -la"


# ---------------------------------------------------------------------------
# test_tool_done_normalised
# ---------------------------------------------------------------------------


async def test_tool_done_normalised(tmp_path: Path) -> None:
    """message.part.updated (bash, completed) → bus gets tool.bash_done."""
    client = _make_client(tmp_path)
    bus = EventBus()

    raw = _raw_event(
        "message.part.updated",
        {
            "sessionID": _OWN_SESSION,
            "part": {
                "type": "tool",
                "tool": "bash",
                "state": {
                    "status": "completed",
                    "input": {
                        "command": "ls -la",
                        "description": "List files",
                    },
                    "metadata": {
                        "exit": 0,
                    },
                    "time": {
                        "start": 1779784977098,
                        "end": 1779784977101,
                    },
                },
            },
            "time": 1779784977101,
        },
    )

    received = await _run_subscription_with_events(client, bus, [raw])
    assert any(e["type"] == "tool.bash_done" for e in received), (
        f"Expected tool.bash_done in bus, got: {received}"
    )
    events = [e for e in received if e["type"] == "tool.bash_done"]
    assert events[0]["command"] == "ls -la"
    assert events[0]["exit_code"] == 0
    assert events[0]["elapsed_ms"] == 3  # 1779784977101 - 1779784977098


# ---------------------------------------------------------------------------
# test_file_written_normalised
# ---------------------------------------------------------------------------


async def test_file_written_normalised(tmp_path: Path) -> None:
    """message.part.updated (apply_patch, completed, metadata.files) -> tool.file_written."""
    client = _make_client(tmp_path)
    bus = EventBus()

    raw = _raw_event(
        "message.part.updated",
        {
            "sessionID": _OWN_SESSION,
            "part": {
                "type": "tool",
                "tool": "apply_patch",
                "state": {
                    "status": "completed",
                    "input": {
                        "patchText": "*** Begin Patch\n*** End Patch",
                    },
                    "metadata": {
                        "files": [
                            {
                                "filePath": "/workspace/hello.txt",
                                "relativePath": "hello.txt",
                                "type": "add",
                                "additions": 1,
                                "deletions": 0,
                            }
                        ],
                    },
                    "time": {
                        "start": 1779784985515,
                        "end": 1779784985520,
                    },
                },
            },
            "time": 1779784985520,
        },
    )

    received = await _run_subscription_with_events(client, bus, [raw])
    assert any(e["type"] == "tool.file_written" for e in received), (
        f"Expected tool.file_written in bus, got: {received}"
    )
    events = [e for e in received if e["type"] == "tool.file_written"]
    assert events[0]["file"] == "hello.txt"
    assert events[0]["op"] == "add"
    assert events[0]["additions"] == 1
    assert events[0]["deletions"] == 0
    assert events[0]["elapsed_ms"] == 5  # 985520 - 985515


# ---------------------------------------------------------------------------
# test_heartbeat_not_published
# ---------------------------------------------------------------------------


async def test_heartbeat_not_published(tmp_path: Path) -> None:
    """server.heartbeat resets the timer but does NOT publish anything to the bus."""
    client = _make_client(tmp_path)
    bus = EventBus()

    raw = _raw_event("server.heartbeat", {})

    received = await _run_subscription_with_events(client, bus, [raw])
    assert received == [], f"Expected no events from heartbeat, got: {received}"


# ---------------------------------------------------------------------------
# test_reconnect_on_heartbeat_timeout
# ---------------------------------------------------------------------------


async def test_reconnect_on_heartbeat_timeout(tmp_path: Path) -> None:
    """If server.heartbeat is absent for >30s, the client reconnects (new SSE connection)."""
    client = _make_client(tmp_path)
    bus = EventBus()

    connect_calls: list[Any] = []
    call_count = 0

    def _fake_connect_sse(http_client, method, url, **kwargs):
        nonlocal call_count
        call_count += 1
        this_call = call_count
        connect_calls.append(this_call)

        class FakeSSEResponse:
            async def aiter_sse(self):
                # First connection: yields nothing (simulates silence → triggers reconnect).
                # Second connection: yields a heartbeat then hangs long enough to be cancelled.
                if this_call == 1:
                    # Hang for longer than the heartbeat_timeout so the watchdog fires.
                    await asyncio.sleep(10)
                else:
                    yield _raw_event("server.heartbeat", {})
                    await asyncio.sleep(10)

        class FakeCtx:
            async def __aenter__(self):
                return FakeSSEResponse()

            async def __aexit__(self, *args):
                pass

        return FakeCtx()

    # Use a very short heartbeat_timeout so we don't actually wait 30s.
    _TIMEOUT = 0.05  # 50ms

    with (
        patch("backend.opencode_client.aconnect_sse", side_effect=_fake_connect_sse),
        patch("backend.opencode_client.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_http

        task = asyncio.create_task(client.start_event_subscription(bus, heartbeat_timeout=_TIMEOUT))

        # Wait long enough for: first connection → timeout → reconnect → second connection.
        await asyncio.sleep(_TIMEOUT * 5)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # At least two connections must have been opened (original + reconnect).
    assert len(connect_calls) >= 2, (
        f"Expected >=2 SSE connections (reconnect), got {len(connect_calls)}"
    )
