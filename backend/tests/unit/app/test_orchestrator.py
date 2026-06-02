"""Unit tests for orchestrator.py -- N1-S04.

TDD: tests written before the implementation is extended.

Acceptance criteria covered:
- Given the machine, when it runs, then states ``setup`` and ``profiling`` exist with
  a single legal transition between them.
- Given a state is entered, when the transition completes, then ``stage.changed`` is
  published and the transition is persisted via the state store.
- Given setup completes, when the orchestrator advances, then it auto-triggers the
  profiling turn via the narrow ``client.prompt(...)`` interface (not ``httpx``
  directly).

Architecture constraints verified:
- ``httpx`` is NOT imported in ``orchestrator.py``.
- ``client.prompt(session_id, text, schema=None)`` is the only path to OpenCode.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from backend.event_bus import EventBus
from backend.orchestrator import Orchestrator
from backend.state_manager import StateManager

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_state_manager(tmp_path: Path, *, session_id: str | None = "sess-abc") -> StateManager:
    """Return a StateManager initialised in tmp_path."""
    sm = StateManager(path=tmp_path / "state.json")
    sm.load()
    if session_id is not None:
        sm.update(opencode_session_id=session_id)
    return sm


def _make_orchestrator(
    tmp_path: Path,
    *,
    session_id: str | None = "sess-abc",
) -> tuple[Orchestrator, StateManager, EventBus, AsyncMock]:
    """Return a fully-wired Orchestrator with mock client, state manager, and event bus."""
    sm = _make_state_manager(tmp_path, session_id=session_id)
    bus = EventBus()
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(return_value=None)
    orch = Orchestrator(state_manager=sm, bus=bus, client=mock_client)
    return orch, sm, bus, mock_client


# ---------------------------------------------------------------------------
# test_setup_complete_transitions_to_profiling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_complete_transitions_to_profiling(tmp_path):
    """setup_complete() must persist stage=profiling via state_manager.update().

    Acceptance: Given a state is entered, when the transition completes, then the
    transition is persisted via the state store.
    """
    orch, sm, bus, client = _make_orchestrator(tmp_path)

    await orch.setup_complete(dataset="data.csv", aim="Understand churn")

    # Allow any fire-and-forget tasks to run.
    await asyncio.sleep(0)

    state = sm.get_state()
    assert state["stage"] == "profiling", f"Expected 'profiling', got {state['stage']!r}"
    assert state["dataset"] == "data.csv"
    assert state["aim"] == "Understand churn"


# ---------------------------------------------------------------------------
# test_setup_complete_emits_stage_changed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_complete_emits_stage_changed(tmp_path):
    """setup_complete() must publish ``stage.changed`` with payload ``{stage: profiling}``.

    Acceptance: Given a state is entered, when the transition completes, then
    ``stage.changed`` is published.

    The EventBus.subscribe() returns a _Subscription async iterator; __anext__ yields
    the next event.  The event envelope has ``type`` merged at top level alongside
    the payload fields (see event_bus.py: ``{"type": event_type, **payload}``).
    """
    orch, sm, bus, client = _make_orchestrator(tmp_path)

    # Subscribe before calling setup_complete so we don't miss the event.
    sub = bus.subscribe()

    await orch.setup_complete(dataset="data.csv", aim="Understand churn")

    # Allow any fire-and-forget tasks to run.
    await asyncio.sleep(0)

    # _Subscription is an AsyncIterator; __anext__ returns the next queued event.
    event = await sub.__anext__()

    assert event["type"] == "stage.changed", f"Expected 'stage.changed', got {event['type']!r}"
    assert event.get("stage") == "profiling", f"Unexpected event payload: {event}"


# ---------------------------------------------------------------------------
# test_profile_turn_triggered_with_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profile_turn_triggered_with_session(tmp_path):
    """When a session_id is present, client.prompt() must be called after setup_complete().

    Acceptance: Given setup completes, when the orchestrator advances, then it
    auto-triggers the profiling turn via the narrow ``client.prompt(...)`` interface.
    """
    orch, sm, bus, client = _make_orchestrator(tmp_path, session_id="sess-abc")

    await orch.setup_complete(dataset="data.csv", aim="Understand churn")

    # Allow the fire-and-forget task to complete.
    await asyncio.sleep(0)

    client.prompt.assert_awaited_once()
    # First positional arg must be the session ID.
    args, kwargs = client.prompt.call_args
    assert args[0] == "sess-abc", f"Expected session_id 'sess-abc', got {args[0]!r}"
    # Second positional arg is the prompt text (must be a non-empty string).
    prompt_text = args[1]
    assert isinstance(prompt_text, str) and len(prompt_text) > 0, "Prompt text must be non-empty"


# ---------------------------------------------------------------------------
# test_profile_turn_not_triggered_without_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profile_turn_not_triggered_without_session(tmp_path):
    """When no session_id is stored, client.prompt() must NOT be called.

    Acceptance: Given setup completes with no session, when the orchestrator
    advances, then no profile turn is fired (guard condition).
    """
    orch, sm, bus, client = _make_orchestrator(tmp_path, session_id=None)

    await orch.setup_complete(dataset="data.csv", aim="Understand churn")

    # Allow any tasks to run.
    await asyncio.sleep(0)

    client.prompt.assert_not_awaited()


# ---------------------------------------------------------------------------
# test_no_httpx_import
# ---------------------------------------------------------------------------


def test_no_httpx_import():
    """orchestrator.py must not import ``httpx`` directly (architecture boundary).

    Architecture constraint (backlog): the state machine never imports ``httpx``;
    only the OpenCode client may do so.

    This is verified statically by parsing the AST of orchestrator.py — no module
    import or runtime side-effect needed.
    """
    orchestrator_path = Path(__file__).parent.parent.parent.parent / "orchestrator.py"
    assert orchestrator_path.exists(), f"orchestrator.py not found at {orchestrator_path}"

    source = orchestrator_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "httpx" and not alias.name.startswith("httpx."), (
                    f"orchestrator.py must not import httpx (found: 'import {alias.name}')"
                )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert not module.startswith("httpx"), (
                f"orchestrator.py must not import from httpx (found: 'from {module} import ...')"
            )


# ---------------------------------------------------------------------------
# N1-S18 integration: _handle_profile_idle and start_bus_listener
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_profile_idle_emits_profile_ready(tmp_path):
    """When profile.json exists and stage is profiling, profile.ready must be emitted.

    Integration wiring: session.idle → read profile.json → emit profile.ready.
    """
    orch, sm, bus, client = _make_orchestrator(tmp_path)

    # Put orchestrator in profiling stage.
    sm.update(stage="profiling")

    # Write a valid profile.json in the workspace root.
    profile_data = {
        "shape": {"rows": 100, "columns": 5},
        "columns": [
            {"name": "id", "type": "numeric", "flags": [], "summary": "row id"},
        ],
        "flags": [],
    }
    (tmp_path / "profile.json").write_text(__import__("json").dumps(profile_data), encoding="utf-8")

    # Arrange: create orchestrator with workspace_root = tmp_path.
    sm2 = _make_state_manager(tmp_path, session_id="sess-abc")
    sm2.update(stage="profiling")
    bus2 = EventBus()
    mock_client = AsyncMock()
    orch2 = Orchestrator(state_manager=sm2, bus=bus2, client=mock_client, workspace_root=tmp_path)

    sub = bus2.subscribe()

    await orch2._handle_profile_idle()

    event = await sub.__anext__()
    assert event["type"] == "profile.ready", f"Expected 'profile.ready', got {event['type']!r}"
    assert "profile" in event, "profile.ready must include profile data"
    assert event["profile"]["shape"]["rows"] == 100


@pytest.mark.asyncio
async def test_handle_profile_idle_wrong_stage_no_emit(tmp_path):
    """When stage is not profiling, session.idle must not trigger profile.ready."""
    sm = _make_state_manager(tmp_path, session_id="sess-abc")
    sm.update(stage="setup")
    bus = EventBus()
    mock_client = AsyncMock()
    orch = Orchestrator(state_manager=sm, bus=bus, client=mock_client, workspace_root=tmp_path)

    # Write a profile.json so the absence of the file is not the cause.
    import json

    profile_data = {"shape": {"rows": 10, "columns": 2}, "columns": [], "flags": []}
    (tmp_path / "profile.json").write_text(json.dumps(profile_data), encoding="utf-8")

    sub = bus.subscribe()

    await orch._handle_profile_idle()

    # Queue should be empty — no event emitted.
    assert sub._queue.empty(), "profile.ready must NOT be emitted when stage != profiling"


@pytest.mark.asyncio
async def test_handle_profile_idle_missing_file_no_emit(tmp_path):
    """When profile.json is absent, profile.ready must not be emitted (graceful)."""
    sm = _make_state_manager(tmp_path, session_id="sess-abc")
    sm.update(stage="profiling")
    bus = EventBus()
    mock_client = AsyncMock()
    orch = Orchestrator(state_manager=sm, bus=bus, client=mock_client, workspace_root=tmp_path)

    # Do NOT write profile.json.
    sub = bus.subscribe()

    await orch._handle_profile_idle()

    assert sub._queue.empty(), "profile.ready must NOT be emitted when profile.json is missing"


@pytest.mark.asyncio
async def test_start_bus_listener_routes_session_idle(tmp_path):
    """start_bus_listener() must emit profile.ready when session.idle fires in profiling stage.

    The test verifies the full chain: bus listener task receives session.idle →
    calls _handle_profile_idle → emits profile.ready.
    """
    import json

    sm = _make_state_manager(tmp_path, session_id="sess-abc")
    sm.update(stage="profiling")
    bus = EventBus()
    mock_client = AsyncMock()
    orch = Orchestrator(state_manager=sm, bus=bus, client=mock_client, workspace_root=tmp_path)

    profile_data = {
        "shape": {"rows": 42, "columns": 3},
        "columns": [{"name": "x", "type": "numeric", "flags": [], "summary": "col x"}],
        "flags": [],
    }
    (tmp_path / "profile.json").write_text(json.dumps(profile_data), encoding="utf-8")

    # Subscribe before starting the listener so we capture all events.
    sub = bus.subscribe()

    # Start the listener as a task so it subscribes to the bus.
    listener_task = asyncio.create_task(orch.start_bus_listener())
    # Yield so the task starts and registers its bus subscription.
    await asyncio.sleep(0)

    # Publish session.idle to trigger the handler.
    await bus.publish("session.idle", {"ts": 12345})

    # Wait for profile.ready with a short timeout; collect up to 2 events.
    # The first event seen by sub may be session.idle itself; profile.ready follows.
    received_types = []
    try:
        for _ in range(2):
            event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
            received_types.append(event["type"])
            if event["type"] == "profile.ready":
                profile_ready_event = event
                break
    except asyncio.TimeoutError:
        pass

    # Cancel the listener.
    listener_task.cancel()
    try:
        await listener_task
    except asyncio.CancelledError:
        pass

    assert "profile.ready" in received_types, (
        f"Expected 'profile.ready' in events; got: {received_types}"
    )
    assert profile_ready_event["profile"]["shape"]["rows"] == 42  # type: ignore[possibly-undefined]


# ---------------------------------------------------------------------------
# re_profile — error paths and happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_re_profile_raises_without_session(tmp_path):
    """re_profile() raises ValueError when no session_id is stored."""
    sm = _make_state_manager(tmp_path, session_id=None)
    sm.update(stage="profiling")
    mock_client = AsyncMock()
    orch = Orchestrator(state_manager=sm, bus=EventBus(), client=mock_client)

    with pytest.raises(ValueError, match="No active session"):
        await orch.re_profile("look at the age column")


@pytest.mark.asyncio
async def test_re_profile_raises_wrong_stage(tmp_path):
    """re_profile() raises ValueError when stage is not profiling."""
    orch, sm, bus, client = _make_orchestrator(tmp_path, session_id="sess-abc")
    sm.update(stage="setup")

    with pytest.raises(ValueError, match="profiling"):
        await orch.re_profile("look at the age column")


@pytest.mark.asyncio
async def test_re_profile_fires_prompt(tmp_path):
    """re_profile() dispatches client.prompt with the session id and a non-empty prompt."""
    orch, sm, bus, client = _make_orchestrator(tmp_path, session_id="sess-abc")
    sm.update(stage="profiling", dataset="data.csv", aim="find patterns")

    await orch.re_profile("focus on the age column")
    await asyncio.sleep(0)

    client.prompt.assert_awaited_once()
    args, _ = client.prompt.call_args
    assert args[0] == "sess-abc"
    assert isinstance(args[1], str) and len(args[1]) > 0


# ---------------------------------------------------------------------------
# setup_complete with client=None (SKIP_OPENCODE path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_complete_skips_turn_without_client(tmp_path):
    """setup_complete() must not crash and must not call prompt when client=None."""
    sm = _make_state_manager(tmp_path, session_id="sess-abc")
    bus = EventBus()
    orch = Orchestrator(state_manager=sm, bus=bus, client=None)

    # Must not raise even though client is None.
    await orch.setup_complete(dataset="data.csv", aim="find patterns")
    await asyncio.sleep(0)

    # Stage transition still persisted.
    assert sm.get_state()["stage"] == "profiling"
