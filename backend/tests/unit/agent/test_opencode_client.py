"""Unit tests for opencode_client.py — OpenCodeClient lifecycle.

TDD: these tests were written before the implementation.

Acceptance criteria covered:
- Binary resolution raises clearly when opencode is not found.
- Readiness polling: start() completes when GET /health returns 200.
- Session creation: POST /session returns session ID which is persisted to state.
- Shutdown: stop() terminates the process cleanly.

The real OpenCode process cannot run in unit tests.  All subprocess and HTTP
calls are mocked via unittest.mock.AsyncMock and patch.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agent.opencode_client import OpenCodeClient
from backend.core.state_manager import StateManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state_manager(tmp_path: Path) -> StateManager:
    """Return a StateManager pointing at a temp directory."""
    sm = StateManager(path=tmp_path / "state.json")
    return sm


def _make_mock_process() -> MagicMock:
    """Return a mock asyncio.subprocess.Process that is alive (returncode=None)."""
    process = MagicMock()
    process.returncode = None  # alive
    process.terminate = MagicMock()
    process.kill = MagicMock()
    # wait() must be awaitable
    process.wait = AsyncMock(return_value=0)
    return process


# ---------------------------------------------------------------------------
# test_binary_not_found_raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_binary_not_found_raises(tmp_path: Path) -> None:
    """start() raises RuntimeError with a clear message when opencode binary is absent."""
    sm = _make_state_manager(tmp_path)
    client = OpenCodeClient(state_manager=sm)

    with patch("shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="opencode"):
            await client.start()


# ---------------------------------------------------------------------------
# test_readiness_poll_success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_readiness_poll_success(tmp_path: Path) -> None:
    """start() completes when the health endpoint returns 200 after one poll."""
    sm = _make_state_manager(tmp_path)
    client = OpenCodeClient(state_manager=sm)

    mock_process = _make_mock_process()

    # Health response: 200 OK on the first call.
    mock_health_response = MagicMock()
    mock_health_response.status_code = 200

    # Session create response: valid session JSON.
    mock_session_response = MagicMock()
    mock_session_response.status_code = 200
    mock_session_response.json = MagicMock(return_value={"id": "sess-readiness-test"})

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=False)
    # First call → health check, second call → session create
    mock_http_client.get = AsyncMock(return_value=mock_health_response)
    mock_http_client.post = AsyncMock(return_value=mock_session_response)

    with (
        patch("shutil.which", return_value="/usr/local/bin/opencode"),
        patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec,
        patch("httpx.AsyncClient", return_value=mock_http_client),
    ):
        await client.start()

    # Subprocess was launched.
    mock_exec.assert_called_once()
    # Health endpoint was polled.
    mock_http_client.get.assert_called_once()
    # session_id was recorded.
    assert client.session_id == "sess-readiness-test"


# ---------------------------------------------------------------------------
# test_session_created_and_persisted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_created_and_persisted(tmp_path: Path) -> None:
    """start() persists the session ID to state via StateManager.update()."""
    sm = _make_state_manager(tmp_path)
    client = OpenCodeClient(state_manager=sm)

    mock_process = _make_mock_process()

    mock_health_response = MagicMock()
    mock_health_response.status_code = 200

    session_payload = {"id": "sess-123"}
    mock_session_response = MagicMock()
    mock_session_response.status_code = 200
    mock_session_response.json = MagicMock(return_value=session_payload)

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=False)
    mock_http_client.get = AsyncMock(return_value=mock_health_response)
    mock_http_client.post = AsyncMock(return_value=mock_session_response)

    with (
        patch("shutil.which", return_value="/usr/local/bin/opencode"),
        patch("asyncio.create_subprocess_exec", return_value=mock_process),
        patch("httpx.AsyncClient", return_value=mock_http_client),
        patch.object(sm, "update", wraps=sm.update) as mock_update,
    ):
        await client.start()

    # The state manager must have been called with the session ID.
    mock_update.assert_called_once_with(opencode_session_id="sess-123")

    # Also check the property.
    assert client.session_id == "sess-123"


# ---------------------------------------------------------------------------
# test_stop_terminates_process
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_terminates_process(tmp_path: Path) -> None:
    """stop() calls process.terminate() and awaits process.wait()."""
    sm = _make_state_manager(tmp_path)
    client = OpenCodeClient(state_manager=sm)

    mock_process = _make_mock_process()
    # After terminate(), wait() returns quickly (process exited).
    mock_process.wait = AsyncMock(return_value=0)

    mock_health_response = MagicMock()
    mock_health_response.status_code = 200

    mock_session_response = MagicMock()
    mock_session_response.status_code = 200
    mock_session_response.json = MagicMock(return_value={"id": "sess-stop-test"})

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=False)
    mock_http_client.get = AsyncMock(return_value=mock_health_response)
    mock_http_client.post = AsyncMock(return_value=mock_session_response)

    with (
        patch("shutil.which", return_value="/usr/local/bin/opencode"),
        patch("asyncio.create_subprocess_exec", return_value=mock_process),
        patch("httpx.AsyncClient", return_value=mock_http_client),
    ):
        await client.start()
        await client.stop()

    mock_process.terminate.assert_called_once()
    mock_process.wait.assert_awaited()


# ---------------------------------------------------------------------------
# test_stop_is_safe_when_not_started
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_is_safe_when_not_started(tmp_path: Path) -> None:
    """stop() does not raise if start() was never called."""
    sm = _make_state_manager(tmp_path)
    client = OpenCodeClient(state_manager=sm)
    # Must not raise.
    await client.stop()


# ---------------------------------------------------------------------------
# test_readiness_timeout_raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_readiness_timeout_raises(tmp_path: Path) -> None:
    """start() raises RuntimeError when health endpoint never returns 200 within timeout."""
    sm = _make_state_manager(tmp_path)
    # Use a very short timeout so the test doesn't actually wait.
    client = OpenCodeClient(state_manager=sm, readiness_timeout=0.1, poll_interval=0.05)

    mock_process = _make_mock_process()

    mock_health_response = MagicMock()
    mock_health_response.status_code = 503  # Never ready

    mock_http_client = AsyncMock()
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=False)
    mock_http_client.get = AsyncMock(return_value=mock_health_response)

    with (
        patch("shutil.which", return_value="/usr/local/bin/opencode"),
        patch("asyncio.create_subprocess_exec", return_value=mock_process),
        patch("httpx.AsyncClient", return_value=mock_http_client),
        pytest.raises(RuntimeError, match="timed out"),
    ):
        await client.start()
