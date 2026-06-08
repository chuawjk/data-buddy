"""Unit tests for watchdog.py -- Watchdog stuck-turn detection and recovery.

TDD: tests written before implementation.

Acceptance criteria covered:
- test_timeout_triggers_abort: after WATCHDOG_TIMEOUT seconds of silence, client.abort() called.
- test_fresh_session_after_grace: after abort, client.create_fresh_session() is called.
- test_state_updated_with_new_session: state_manager.update(opencode_session_id=new_id) called.
- test_turn_error_emitted: bus.publish("turn.error", ...) is called.
- test_heartbeat_resets_timer: heartbeat() before timeout means abort is NOT called.
- test_cancel_stops_watch: cancel() before timeout means abort is NOT called.

WATCHDOG_TIMEOUT_SECONDS env var override:
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
    """After recovery, turn.error is published with reason='timeout' and stage."""
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
    assert payload.get("reason") == "timeout", (
        f"Expected reason='timeout'; got {payload.get('reason')!r}"
    )
    assert "stage" in payload, "turn.error from watchdog must include stage"
    assert "retryable" not in payload, "turn.error must not include legacy retryable field"


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
# test_timeout_env_var_override
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


# ---------------------------------------------------------------------------
# heartbeat preserves the per-turn timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_heartbeat_preserves_timeout() -> None:
    """heartbeat() resets the timer using the same timeout that start_turn() was called with.

    A Watchdog started with timeout=180 stays at 180 after heartbeat,
    not reset to the default 60 (or 1 in test env).

    This verifies the fix for the bug where heartbeat() called start_turn() with no argument,
    silently reverting to WATCHDOG_TIMEOUT even during a 180s section build.
    """
    wmod = _load_watchdog()
    client = _make_client()
    sm = _make_state_manager()
    bus = _make_bus()
    watchdog = wmod.Watchdog(client=client, state_manager=sm, bus=bus)

    seen_timeouts: list[float] = []
    original_sleep = asyncio.sleep
    call_count = 0

    async def recording_sleep(seconds: float) -> None:
        nonlocal call_count
        seen_timeouts.append(seconds)
        call_count += 1
        # Only yield for the first sleep so we can observe the timeout passed.
        await original_sleep(0)

    with unittest.mock.patch("backend.core.watchdog.asyncio.sleep", side_effect=recording_sleep):
        # Start with a 180s section-build timeout.
        watchdog.start_turn(timeout=180)
        await original_sleep(0)
        # heartbeat should re-arm using 180, not WATCHDOG_TIMEOUT (1 in test env).
        watchdog.heartbeat()
        await original_sleep(0.1)

    # The first timeout recorded for the heartbeat's _watch call must be 180.
    # seen_timeouts[0] = first start_turn(180) call
    # seen_timeouts[1] = heartbeat's restart — must also be 180, not WATCHDOG_TIMEOUT
    assert len(seen_timeouts) >= 2, f"Expected at least 2 sleep calls; got {seen_timeouts}"
    assert seen_timeouts[1] == 180, (
        f"heartbeat() must preserve the 180s timeout, not reset to {wmod.WATCHDOG_TIMEOUT}. "
        f"Got: {seen_timeouts[1]}"
    )


@pytest.mark.asyncio
async def test_heartbeat_without_armed_turn_is_noop() -> None:
    """heartbeat() before any start_turn() is a no-op — it does not arm the watchdog.

    Activity that arrives between turns must never start the silence timer by
    itself; only start_turn() arms it.
    """
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
        watchdog.heartbeat()
        await original_sleep(0.1)

    # No timer armed → no sleep, no abort/recovery.
    assert seen_timeouts == [], f"heartbeat() with no armed turn must not arm; got {seen_timeouts}"
    client.abort.assert_not_awaited()


@pytest.mark.asyncio
async def test_heartbeat_after_cancel_is_noop() -> None:
    """Once a turn ends (cancel), heartbeat() no longer re-arms the watchdog."""
    wmod = _load_watchdog()
    client = _make_client()
    sm = _make_state_manager()
    bus = _make_bus()
    watchdog = wmod.Watchdog(client=client, state_manager=sm, bus=bus)

    watchdog.start_turn()
    await asyncio.sleep(0.001)
    watchdog.cancel()
    await asyncio.sleep(0.001)
    # Stray activity after the turn finished must not re-arm.
    watchdog.heartbeat()
    # WATCHDOG_TIMEOUT is 1s in tests; wait past it to prove nothing fired.
    await asyncio.sleep(1.2)

    client.abort.assert_not_awaited()


@pytest.mark.asyncio
async def test_stall_control_shortens_timeout() -> None:
    """When the turn-stall QA control is active, start_turn() uses the short demo window."""
    wmod = _load_watchdog()
    client = _make_client()
    sm = _make_state_manager()
    bus = _make_bus()
    qa = unittest.mock.MagicMock()
    qa.enabled = unittest.mock.MagicMock(return_value=True)
    watchdog = wmod.Watchdog(client=client, state_manager=sm, bus=bus, qa_controls=qa)

    seen_timeouts: list[float] = []
    original_sleep = asyncio.sleep

    async def recording_sleep(seconds: float) -> None:
        seen_timeouts.append(seconds)
        await original_sleep(0)

    with unittest.mock.patch("backend.core.watchdog.asyncio.sleep", side_effect=recording_sleep):
        # Even a long section-build budget collapses to the stall-demo timeout.
        watchdog.start_turn(timeout=180)
        await original_sleep(0.1)

    assert seen_timeouts[0] == wmod._STALL_DEMO_TIMEOUT_S, (
        f"stall control must shorten the timeout to {wmod._STALL_DEMO_TIMEOUT_S}; "
        f"got {seen_timeouts[0]}"
    )


@pytest.mark.asyncio
async def test_stall_control_uses_short_grace() -> None:
    """When stall is active, the post-abort grace period collapses to the short demo value."""
    wmod = _load_watchdog()
    client = _make_client()
    sm = _make_state_manager()
    bus = _make_bus()
    qa = unittest.mock.MagicMock()
    qa.enabled = unittest.mock.MagicMock(return_value=True)
    watchdog = wmod.Watchdog(client=client, state_manager=sm, bus=bus, qa_controls=qa)

    seen_timeouts: list[float] = []
    original_sleep = asyncio.sleep

    async def recording_sleep(seconds: float) -> None:
        seen_timeouts.append(seconds)
        await original_sleep(0)

    with unittest.mock.patch("backend.core.watchdog.asyncio.sleep", side_effect=recording_sleep):
        watchdog.start_turn()
        await original_sleep(0.1)

    # seen_timeouts[0] = silence window; the grace sleep must be the short demo value.
    assert wmod._STALL_GRACE_PERIOD_S in seen_timeouts, (
        f"stall recovery must use the short grace {wmod._STALL_GRACE_PERIOD_S}; got {seen_timeouts}"
    )
    client.abort.assert_awaited_once()
    client.create_fresh_session.assert_awaited_once()
