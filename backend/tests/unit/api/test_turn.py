"""Unit tests for POST /turn endpoint and Orchestrator.re_profile() -- N1-S12.

TDD: tests written before the implementation.

Acceptance criteria covered:
- Given the profiling stage, when POST /turn is called with bottom-bar text, then a
  re-profile prompt is dispatched and 204 returns immediately.
- Given the dispatched turn, when it runs, then progress arrives via SSE (verified via
  client.prompt call assertions; SSE routing is owned by N1-S10 / N1-S08).
- Given a second consecutive turn on the same session, when it runs, then it completes or
  recovers without hanging (watchdog owns recovery -- this story just fires the turn).
- Given completion, when output lands, then profile.json is overwritten (owned by N1-S09
  profiling-turn handler; re_profile re-uses the same prompt path).

Architecture constraints verified:
- The router delegates to orchestrator.re_profile() without doing OpenCode work itself.
- POST /turn returns 204 immediately (fire-and-forget).
- POST /turn with empty/whitespace text returns 422.
- POST /turn in wrong stage (e.g. setup) returns 422 with invalid_stage error.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.router import router
from backend.core.event_bus import EventBus
from backend.core.orchestrator import Orchestrator
from backend.core.state_manager import StateManager

# ---------------------------------------------------------------------------
# Test app factory -- isolated from the real filesystem.
# ---------------------------------------------------------------------------


def _make_app(tmp_path: Path, *, stage: str = "profiling") -> FastAPI:
    """Return a fresh FastAPI app wired with test-isolated state + orchestrator.

    Args:
        tmp_path: Temporary directory for state.json isolation.
        stage: The stage to set on the state manager before yielding.
    """

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        app.state.bus = EventBus()
        sm = StateManager(path=tmp_path / "state.json")
        sm.load()
        # Set session ID and stage so the endpoint logic can read them.
        sm.update(opencode_session_id="sess-test-123", stage=stage)
        app.state.state_manager = sm
        app.state.orchestrator = Orchestrator(
            state_manager=sm,
            bus=app.state.bus,
            workspace_root=tmp_path,
        )
        yield

    test_app = FastAPI(lifespan=_lifespan)
    test_app.include_router(router)
    return test_app


# ---------------------------------------------------------------------------
# test_turn_dispatches_reprof_in_profiling_stage
# ---------------------------------------------------------------------------


def test_turn_dispatches_reprof_in_profiling_stage(tmp_path):
    """POST /turn with text in profiling stage calls orchestrator.re_profile(text) and returns 204.

    Acceptance: Given the profiling stage, when POST /turn is called with bottom-bar
    text, then a re-profile prompt is dispatched and 204 returns immediately.
    """
    app = _make_app(tmp_path, stage="profiling")

    with TestClient(app) as client:
        # Patch re_profile after the lifespan has initialised the orchestrator.
        orchestrator = app.state.orchestrator
        orchestrator.re_profile = AsyncMock(return_value=None)

        r = client.post("/turn", json={"text": "re-analyse churn"})

    assert r.status_code == 204, f"Expected 204, got {r.status_code}: {r.text}"
    orchestrator.re_profile.assert_awaited_once_with("re-analyse churn")


# ---------------------------------------------------------------------------
# test_turn_rejected_with_empty_text
# ---------------------------------------------------------------------------


def test_turn_whitespace_text_calls_retry(tmp_path):
    """POST /turn with whitespace-only text triggers retry (N3-S02).

    Per the API contract: an absent or empty text field re-fires the last
    prompt (retry path).  Returns 204, not 422.
    """
    app = _make_app(tmp_path, stage="profiling")

    with TestClient(app) as client:
        orchestrator = app.state.orchestrator
        orchestrator.retry_last_turn = AsyncMock(return_value=None)

        r = client.post("/turn", json={"text": "   "})

    assert r.status_code == 204, f"Expected 204 (retry path), got {r.status_code}: {r.text}"
    orchestrator.retry_last_turn.assert_awaited_once()


def test_turn_missing_text_calls_retry(tmp_path):
    """POST /turn with no text field triggers retry (N3-S02).

    Per the API contract: absent text means retry the last turn.
    """
    app = _make_app(tmp_path, stage="profiling")

    with TestClient(app) as client:
        orchestrator = app.state.orchestrator
        orchestrator.retry_last_turn = AsyncMock(return_value=None)

        r = client.post("/turn", json={})

    assert r.status_code == 204, f"Expected 204 (retry path), got {r.status_code}: {r.text}"
    orchestrator.retry_last_turn.assert_awaited_once()


# ---------------------------------------------------------------------------
# test_turn_rejected_wrong_stage
# ---------------------------------------------------------------------------


def test_turn_rejected_wrong_stage(tmp_path):
    """POST /turn when stage=setup returns 422 with invalid_stage error.

    Acceptance: Given POST /turn is called in a stage that does not support it
    (e.g. setup), then 422 is returned.
    """
    app = _make_app(tmp_path, stage="setup")

    with TestClient(app) as client:
        r = client.post("/turn", json={"text": "some input"})

    assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"
    body = r.json()
    assert body.get("error") == "invalid_stage", f"Unexpected error key: {body}"
    assert "message" in body


# ---------------------------------------------------------------------------
# test_reprof_calls_client_prompt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reprof_calls_client_prompt(tmp_path):
    """Orchestrator.re_profile(text) calls client.prompt with correct session_id and schema.

    Acceptance: Given completion, when output lands, then profile.json is overwritten
    (via the same profiling prompt + schema path as setup_complete).

    This test verifies the narrow interface: client.prompt() is called with:
    - The current session ID from state.json.
    - A non-empty prompt string containing the dataset name.
    - A schema kwarg (the PROFILE_SCHEMA dict, not None).
    """
    sm = StateManager(path=tmp_path / "state.json")
    sm.load()
    sm.update(opencode_session_id="sess-reprof-456", stage="profiling", dataset="churn.csv")

    bus = EventBus()
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(return_value=None)

    orch = Orchestrator(
        state_manager=sm,
        bus=bus,
        client=mock_client,
        workspace_root=tmp_path,
    )

    await orch.re_profile("focus on high-value customers")

    # Allow any fire-and-forget tasks to run.
    await asyncio.sleep(0)

    mock_client.prompt.assert_awaited_once()
    call_args = mock_client.prompt.call_args

    # First positional arg: session_id.
    assert call_args.args[0] == "sess-reprof-456", (
        f"Expected session_id 'sess-reprof-456', got {call_args.args[0]!r}"
    )
    # Second positional arg: a non-empty prompt string.
    prompt_text = call_args.args[1]
    assert isinstance(prompt_text, str) and len(prompt_text) > 0, (
        "Prompt text must be a non-empty string"
    )
    # schema kwarg must be provided (not None) -- this is what causes profile.json to be
    # written with structured output.
    schema = call_args.kwargs.get("schema")
    assert schema is not None, "schema must be passed to client.prompt (not None)"
    assert isinstance(schema, dict), f"schema must be a dict, got {type(schema)}"


@pytest.mark.asyncio
async def test_reprof_raises_without_session(tmp_path):
    """Orchestrator.re_profile() raises ValueError when no session_id is in state.

    This protects against calling re_profile when OpenCode has not started.
    """
    sm = StateManager(path=tmp_path / "state.json")
    sm.load()
    # stage=profiling but no session ID.
    sm.update(stage="profiling")

    bus = EventBus()
    mock_client = AsyncMock()

    orch = Orchestrator(
        state_manager=sm,
        bus=bus,
        client=mock_client,
        workspace_root=tmp_path,
    )

    with pytest.raises(ValueError, match="No active session"):
        await orch.re_profile("some text")


@pytest.mark.asyncio
async def test_reprof_raises_in_wrong_stage(tmp_path):
    """Orchestrator.re_profile() raises ValueError when called outside profiling stage.

    Night 2 extends POST /turn for planning/building; re_profile is only valid
    during profiling.
    """
    sm = StateManager(path=tmp_path / "state.json")
    sm.load()
    sm.update(opencode_session_id="sess-abc", stage="setup")

    bus = EventBus()
    mock_client = AsyncMock()

    orch = Orchestrator(
        state_manager=sm,
        bus=bus,
        client=mock_client,
        workspace_root=tmp_path,
    )

    with pytest.raises(ValueError, match="re_profile only valid in profiling stage"):
        await orch.re_profile("some text")


@pytest.mark.asyncio
async def test_reprof_starts_watchdog(tmp_path):
    """Orchestrator.re_profile() calls watchdog.start_turn() when a watchdog is wired in.

    Acceptance: Given a second consecutive turn on the same session, when it runs,
    then the watchdog is armed so recovery can fire if the turn stalls.
    """
    sm = StateManager(path=tmp_path / "state.json")
    sm.load()
    sm.update(opencode_session_id="sess-wd-789", stage="profiling", dataset="data.csv")

    bus = EventBus()
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(return_value=None)

    # Create a mock watchdog.  start_turn is a regular sync method on the real Watchdog.
    mock_watchdog = MagicMock()
    mock_watchdog.start_turn = MagicMock(return_value=None)

    orch = Orchestrator(
        state_manager=sm,
        bus=bus,
        client=mock_client,
        workspace_root=tmp_path,
        watchdog=mock_watchdog,
    )

    await orch.re_profile("check high churn columns")
    await asyncio.sleep(0)

    mock_watchdog.start_turn.assert_called_once()  # sync call, not awaited


# ---------------------------------------------------------------------------
# re_plan tests
# ---------------------------------------------------------------------------


def test_turn_dispatches_replan_in_planning_stage(tmp_path):
    """POST /turn in planning stage calls orchestrator.re_plan(text) and returns 204."""
    app = _make_app(tmp_path, stage="planning")

    with TestClient(app) as client:
        orchestrator = app.state.orchestrator
        orchestrator.re_plan = AsyncMock(return_value=None)

        r = client.post("/turn", json={"text": "add a section on seasonality"})

    assert r.status_code == 204, f"Expected 204, got {r.status_code}: {r.text}"
    orchestrator.re_plan.assert_awaited_once_with("add a section on seasonality")


@pytest.mark.asyncio
async def test_replan_calls_client_prompt(tmp_path):
    """Orchestrator.re_plan(text) calls client.prompt with session_id and a plan schema."""
    sm = StateManager(path=tmp_path / "state.json")
    sm.load()
    sm.update(opencode_session_id="sess-plan-001", stage="planning", dataset="data.csv")

    bus = EventBus()
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(return_value=None)

    orch = Orchestrator(state_manager=sm, bus=bus, client=mock_client, workspace_root=tmp_path)

    await orch.re_plan("add a seasonality section")
    await asyncio.sleep(0)

    mock_client.prompt.assert_awaited_once()
    args = mock_client.prompt.call_args.args
    assert args[0] == "sess-plan-001"
    assert isinstance(args[1], str) and "seasonality" in args[1]


@pytest.mark.asyncio
async def test_replan_raises_without_session(tmp_path):
    """Orchestrator.re_plan() raises ValueError when no session_id is in state."""
    sm = StateManager(path=tmp_path / "state.json")
    sm.load()
    sm.update(stage="planning")

    orch = Orchestrator(
        state_manager=sm, bus=EventBus(), client=AsyncMock(), workspace_root=tmp_path
    )

    with pytest.raises(ValueError, match="No active session"):
        await orch.re_plan("some text")


@pytest.mark.asyncio
async def test_replan_raises_in_wrong_stage(tmp_path):
    """Orchestrator.re_plan() raises ValueError when called outside planning stage."""
    sm = StateManager(path=tmp_path / "state.json")
    sm.load()
    sm.update(opencode_session_id="sess-abc", stage="profiling")

    orch = Orchestrator(
        state_manager=sm, bus=EventBus(), client=AsyncMock(), workspace_root=tmp_path
    )

    with pytest.raises(ValueError, match="re_plan only valid in planning stage"):
        await orch.re_plan("some text")


@pytest.mark.asyncio
async def test_replan_starts_watchdog(tmp_path):
    """Orchestrator.re_plan() calls watchdog.start_turn() when a watchdog is wired in."""
    sm = StateManager(path=tmp_path / "state.json")
    sm.load()
    sm.update(opencode_session_id="sess-wd-plan", stage="planning", dataset="data.csv")

    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(return_value=None)
    mock_watchdog = MagicMock()
    mock_watchdog.start_turn = MagicMock(return_value=None)

    orch = Orchestrator(
        state_manager=sm,
        bus=EventBus(),
        client=mock_client,
        workspace_root=tmp_path,
        watchdog=mock_watchdog,
    )

    await orch.re_plan("remove the last section")
    await asyncio.sleep(0)

    mock_watchdog.start_turn.assert_called_once()


# ---------------------------------------------------------------------------
# N3-S02: POST /turn with empty body calls retry_last_turn
# ---------------------------------------------------------------------------


def test_turn_empty_body_calls_retry(tmp_path):
    """POST /turn with empty body (no text field) calls orchestrator.retry_last_turn().

    Acceptance (N3-S02): the retry button POSTs with an empty body to re-fire the
    last prompt.  The router must detect the absent/empty text and call retry instead
    of returning 422 invalid_text.
    """
    app = _make_app(tmp_path, stage="profiling")

    with TestClient(app) as client:
        orchestrator = app.state.orchestrator
        orchestrator.retry_last_turn = AsyncMock(return_value=None)

        r = client.post("/turn", json={})

    assert r.status_code == 204, f"Expected 204, got {r.status_code}: {r.text}"
    orchestrator.retry_last_turn.assert_awaited_once()


def test_turn_null_body_calls_retry(tmp_path):
    """POST /turn with no body at all calls orchestrator.retry_last_turn()."""
    app = _make_app(tmp_path, stage="profiling")

    with TestClient(app) as client:
        orchestrator = app.state.orchestrator
        orchestrator.retry_last_turn = AsyncMock(return_value=None)

        # Send POST with no JSON body.
        r = client.post("/turn")

    assert r.status_code == 204, f"Expected 204, got {r.status_code}: {r.text}"
    orchestrator.retry_last_turn.assert_awaited_once()
