"""Unit tests for watchdog.py -- Watchdog stuck-turn detection and recovery.

TDD: tests written before implementation (N1-S11).

Acceptance criteria covered:
- test_timeout_triggers_abort: after WATCHDOG_TIMEOUT seconds of silence, client.abort() called.
- test_fresh_session_after_grace: after abort, client.create_fresh_session() is called.
- test_state_updated_with_new_session: state_manager.update(opencode_session_id=new_id) called.
- test_turn_error_emitted: bus.publish("turn.error", ...) is called.
- test_heartbeat_resets_timer: heartbeat() before timeout means abort is NOT called.
- test_cancel_stops_watch: cancel() before timeout means abort is NOT called.

N1-S20 seam:
- test_timeout_env_var_override: WATCHDOG_TIMEOUT_SECONDS env var is respected.

WATCHDOG_TIMEOUT_SECONDS=1 is set via monkeypatch (autouse) for fast test execution.
"""

from __future__ import annotations

import asyncio
import importlib
import unittest.mock
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client() -> MagicMock:
    client = MagicMock()
    client.abort = AsyncMock(return_value=None)
    client.create_fresh_session = AsyncMock(return_value="ses_fresh_id")
    return client


def _make_state_manager(session_id: str = "ses_existing_id") -> MagicMock:
    sm = MagicMock()
    sm.get_state = MagicMock(return_value={"opencode_session_id": session_id})
    sm.update = MagicMock()
    return sm


def _make_bus() -> AsyncMock:
    bus = AsyncMock()
    bus.publish = AsyncMock(return_value=None)
    return bus


def _load_watchdog():
    """Reload watchdog module to pick up current env vars."""
    import backend.core.watchdog

    importlib.reload(backend.core.watchdog)
    return backend.core.watchdog


# ---------------------------------------------------------------------------
# Autouse fixture: short timeout for all tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def fast_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WATCHDOG_TIMEOUT_SECONDS", "1")


# ---------------------------------------------------------------------------
# Helper: run a watchdog with instant sleep until the task completes
# ---------------------------------------------------------------------------


async def _run_with_instant_sleep(watchdog) -> None:
    """Start a turn with instant sleep and wait for the recovery to complete."""
    original_sleep = asyncio.sleep

    async def instant_sleep(seconds: float) -> None:
        await original_sleep(0)

    with unittest.mock.patch("backend.core.watchdog.asyncio.sleep", side_effect=instant_sleep):
        watchdog.start_turn()
        # Give the _watch task enough time to complete.
        await original_sleep(0.1)


# ---------------------------------------------------------------------------
# test_timeout_triggers_abort
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_triggers_abort() -> None:
    """After WATCHDOG_TIMEOUT seconds with no heartbeat, client.abort() is called."""
    wmod = _load_watchdog()
    client = _make_client()
    sm = _make_state_manager()
    bus = _make_bus()
    watchdog = wmod.Watchdog(client=client, state_manager=sm, bus=bus)

    await _run_with_instant_sleep(watchdog)

    client.abort.assert_awaited_once_with("ses_existing_id")


# ---------------------------------------------------------------------------
# test_fresh_session_after_grace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fresh_session_after_grace() -> None:
    """After abort(), create_fresh_session() is called (following the grace sleep)."""
    wmod = _load_watchdog()
    client = _make_client()
    sm = _make_state_manager()
    bus = _make_bus()
    watchdog = wmod.Watchdog(client=client, state_manager=sm, bus=bus)

    await _run_with_instant_sleep(watchdog)

    client.create_fresh_session.assert_awaited_once()


# ---------------------------------------------------------------------------
# test_state_updated_with_new_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state_updated_with_new_session() -> None:
    """After fresh session is created, state_manager.update(opencode_session_id=new_id) called."""
    wmod = _load_watchdog()
    client = _make_client()
    sm = _make_state_manager()
    bus = _make_bus()
    watchdog = wmod.Watchdog(client=client, state_manager=sm, bus=bus)

    await _run_with_instant_sleep(watchdog)

    sm.update.assert_called_once_with(opencode_session_id="ses_fresh_id")


# ---------------------------------------------------------------------------
# test_turn_error_emitted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_turn_error_emitted() -> None:
    """After recovery, bus.publish('turn.error', ...) is called."""
    wmod = _load_watchdog()
    client = _make_client()
    sm = _make_state_manager()
    bus = _make_bus()
    watchdog = wmod.Watchdog(client=client, state_manager=sm, bus=bus)

    await _run_with_instant_sleep(watchdog)

    bus.publish.assert_awaited_once()
    event_type = bus.publish.call_args[0][0]
    payload = bus.publish.call_args[0][1]
    assert event_type == "turn.error"
    assert "message" in payload


# ---------------------------------------------------------------------------
# test_heartbeat_resets_timer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_heartbeat_resets_timer() -> None:
    """heartbeat() before the timeout fires means abort is NOT called.

    Uses WATCHDOG_TIMEOUT_SECONDS=1 (autouse fixture).  heartbeat() and cancel()
    are called within milliseconds so the 1s timer never fires.
    """
    wmod = _load_watchdog()
    client = _make_client()
    sm = _make_state_manager()
    bus = _make_bus()
    watchdog = wmod.Watchdog(client=client, state_manager=sm, bus=bus)

    watchdog.start_turn()
    await asyncio.sleep(0.001)
    watchdog.heartbeat()
    await asyncio.sleep(0.001)
    watchdog.cancel()
    await asyncio.sleep(0.001)

    client.abort.assert_not_awaited()


# ---------------------------------------------------------------------------
# test_cancel_stops_watch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_stops_watch() -> None:
    """cancel() before the timeout fires means abort is NOT called."""
    wmod = _load_watchdog()
    client = _make_client()
    sm = _make_state_manager()
    bus = _make_bus()
    watchdog = wmod.Watchdog(client=client, state_manager=sm, bus=bus)

    watchdog.start_turn()
    await asyncio.sleep(0.001)
    watchdog.cancel()
    await asyncio.sleep(0.001)

    client.abort.assert_not_awaited()


# ---------------------------------------------------------------------------
# test_timeout_env_var_override (N1-S20 seam)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_env_var_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """WATCHDOG_TIMEOUT_SECONDS env var is read and used as the timeout value."""
    monkeypatch.setenv("WATCHDOG_TIMEOUT_SECONDS", "42")
    wmod = _load_watchdog()
    assert wmod.WATCHDOG_TIMEOUT == 42


# ---------------------------------------------------------------------------
# test_no_session_id_skips_abort (edge case)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_session_id_skips_abort() -> None:
    """If there is no session ID in state, abort() is not called but turn.error is emitted."""
    wmod = _load_watchdog()
    client = _make_client()
    sm = MagicMock()
    sm.get_state = MagicMock(return_value={"opencode_session_id": None})
    sm.update = MagicMock()
    bus = _make_bus()
    watchdog = wmod.Watchdog(client=client, state_manager=sm, bus=bus)

    await _run_with_instant_sleep(watchdog)

    client.abort.assert_not_awaited()
    client.create_fresh_session.assert_not_awaited()
    bus.publish.assert_awaited_once()
    assert bus.publish.call_args[0][0] == "turn.error"


# ---------------------------------------------------------------------------
# test_start_turn_custom_timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_turn_custom_timeout_fires_after_given_seconds() -> None:
    """start_turn(timeout=N) uses N seconds, not WATCHDOG_TIMEOUT."""
    wmod = _load_watchdog()
    client = _make_client()
    sm = _make_state_manager()
    bus = _make_bus()
    watchdog = wmod.Watchdog(client=client, state_manager=sm, bus=bus)

    seen_timeouts: list[float] = []
    original_sleep = asyncio.sleep

    async def recording_sleep(seconds: float) -> None:
        seen_timeouts.append(seconds)
        await original_sleep(0)

    with unittest.mock.patch("backend.core.watchdog.asyncio.sleep", side_effect=recording_sleep):
        watchdog.start_turn(timeout=180)
        await original_sleep(0.1)

    # The first sleep call is the _watch timeout; it must be 180, not WATCHDOG_TIMEOUT.
    assert seen_timeouts[0] == 180, f"Expected 180s timeout, got {seen_timeouts[0]}"
    client.abort.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_turn_default_timeout_uses_watchdog_timeout() -> None:
    """start_turn() with no argument uses WATCHDOG_TIMEOUT (60 by default, 1 in tests)."""
    wmod = _load_watchdog()
    client = _make_client()
    sm = _make_state_manager()
    bus = _make_bus()
    watchdog = wmod.Watchdog(client=client, state_manager=sm, bus=bus)

    seen_timeouts: list[float] = []
    original_sleep = asyncio.sleep

    async def recording_sleep(seconds: float) -> None:
        seen_timeouts.append(seconds)
        await original_sleep(0)

    with unittest.mock.patch("backend.core.watchdog.asyncio.sleep", side_effect=recording_sleep):
        watchdog.start_turn()
        await original_sleep(0.1)

    assert seen_timeouts[0] == wmod.WATCHDOG_TIMEOUT
