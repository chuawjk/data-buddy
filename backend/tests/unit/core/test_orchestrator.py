"""Unit tests for orchestrator.py -- N1-S04, N2-S01.

TDD: tests written before the implementation is extended.

Acceptance criteria covered (N1-S04):
- Given the machine, when it runs, then states ``setup`` and ``profiling`` exist with
  a single legal transition between them.
- Given a state is entered, when the transition completes, then ``stage.changed`` is
  published and the transition is persisted via the state store.
- Given setup completes, when the orchestrator advances, then it auto-triggers the
  profiling turn via the narrow ``client.prompt(...)`` interface (not ``httpx``
  directly).

Acceptance criteria covered (N2-S01):
- ``profile.ready`` → profiling → planning + ``stage.changed`` emitted.
- Plan prompt auto-triggered via ``client.prompt()`` narrow interface.
- ``watchdog.start_turn()`` called if wired.
- No ``httpx`` import in orchestrator (AST check — shared with N1-S04).

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

from backend.core.event_bus import EventBus
from backend.core.orchestrator import Orchestrator
from backend.core.state_manager import StateManager

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
    orchestrator_path = Path(__file__).parent.parent.parent.parent / "core" / "orchestrator.py"
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


# ---------------------------------------------------------------------------
# N2-S01: profile.ready → planning transition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profile_ready_transitions_to_planning(tmp_path):
    """profile.ready on bus → stage persisted as planning."""
    orch, sm, bus, client = _make_orchestrator(tmp_path)
    sm.update(stage="profiling", dataset="data.csv", aim="find patterns")

    await orch._handle_planning_transition()
    await asyncio.sleep(0)

    assert sm.get_state()["stage"] == "planning"


@pytest.mark.asyncio
async def test_profile_ready_emits_stage_changed(tmp_path):
    """profile.ready → stage.changed published with stage='planning'."""
    orch, sm, bus, client = _make_orchestrator(tmp_path)
    sm.update(stage="profiling", dataset="data.csv", aim="find patterns")

    sub = bus.subscribe()

    await orch._handle_planning_transition()
    await asyncio.sleep(0)

    # Drain events to find stage.changed
    received = []
    try:
        for _ in range(3):
            event = await asyncio.wait_for(sub.__anext__(), timeout=0.5)
            received.append(event)
    except asyncio.TimeoutError:
        pass

    types = [e["type"] for e in received]
    assert "stage.changed" in types, f"Expected stage.changed; got {types}"
    stage_event = next(e for e in received if e["type"] == "stage.changed")
    assert stage_event.get("stage") == "planning"


@pytest.mark.asyncio
async def test_profile_ready_fires_plan_prompt(tmp_path):
    """profile.ready → client.prompt called (plan turn dispatched)."""
    orch, sm, bus, client = _make_orchestrator(tmp_path)
    sm.update(stage="profiling", dataset="data.csv", aim="find patterns")

    await orch._handle_planning_transition()
    # Allow fire-and-forget task to run.
    await asyncio.sleep(0)

    client.prompt.assert_awaited_once()
    args, _ = client.prompt.call_args
    assert args[0] == "sess-abc"
    assert isinstance(args[1], str) and len(args[1]) > 0


@pytest.mark.asyncio
async def test_profile_ready_wrong_stage_returns_early(tmp_path):
    """_handle_planning_transition is a no-op when stage is not profiling."""
    orch, sm, bus, client = _make_orchestrator(tmp_path)
    sm.update(stage="planning")  # already planning

    sub = bus.subscribe()

    await orch._handle_planning_transition()
    await asyncio.sleep(0)

    # No events should have been emitted.
    assert sub._queue.empty(), "No events should be emitted if already in planning stage"
    client.prompt.assert_not_awaited()


@pytest.mark.asyncio
async def test_profile_ready_no_session_id_no_prompt(tmp_path):
    """_handle_planning_transition runs without error when no session_id is stored.

    Stage transition still persists; plan prompt is skipped.
    """
    sm = _make_state_manager(tmp_path, session_id=None)
    sm.update(stage="profiling")
    bus = EventBus()
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(return_value=None)
    orch = Orchestrator(state_manager=sm, bus=bus, client=mock_client)

    await orch._handle_planning_transition()
    await asyncio.sleep(0)

    # Stage still transitions.
    assert sm.get_state()["stage"] == "planning"
    # But prompt is never called.
    mock_client.prompt.assert_not_awaited()


@pytest.mark.asyncio
async def test_profile_ready_client_none_no_crash(tmp_path):
    """_handle_planning_transition completes without error when client=None."""
    sm = _make_state_manager(tmp_path, session_id="sess-abc")
    sm.update(stage="profiling")
    bus = EventBus()
    orch = Orchestrator(state_manager=sm, bus=bus, client=None)

    # Must not raise.
    await orch._handle_planning_transition()
    await asyncio.sleep(0)

    assert sm.get_state()["stage"] == "planning"


@pytest.mark.asyncio
async def test_plan_turn_error_publishes_turn_error(tmp_path):
    """When client.prompt raises in _run_plan_turn, turn.error is emitted on bus."""
    sm = _make_state_manager(tmp_path, session_id="sess-abc")
    sm.update(stage="profiling")
    bus = EventBus()
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(side_effect=RuntimeError("OpenCode unavailable"))
    orch = Orchestrator(state_manager=sm, bus=bus, client=mock_client)

    sub = bus.subscribe()

    await orch._run_plan_turn("sess-abc", "Draft a plan")
    await asyncio.sleep(0)

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "turn.error", f"Expected turn.error; got {event['type']!r}"


# ---------------------------------------------------------------------------
# N2-S02: session.idle in planning stage → plan.json → plan.ready
# ---------------------------------------------------------------------------


def _make_orchestrator_planning(
    tmp_path: Path,
    *,
    session_id: str | None = "sess-abc",
) -> tuple[Orchestrator, StateManager, EventBus, AsyncMock]:
    """Orchestrator pre-set to planning stage."""
    sm = _make_state_manager(tmp_path, session_id=session_id)
    sm.update(stage="planning", dataset="data.csv", aim="find patterns")
    bus = EventBus()
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(return_value=None)
    orch = Orchestrator(state_manager=sm, bus=bus, client=mock_client, workspace_root=tmp_path)
    return orch, sm, bus, mock_client


def _write_valid_plan_json(tmp_path: Path, num_sections: int = 3) -> None:
    """Write a valid plan.json to tmp_path."""
    import json

    sections = [
        {"id": f"sec_{i:02d}", "title": f"Section {i}", "hypothesis": f"Hypothesis {i}"}
        for i in range(1, num_sections + 1)
    ]
    (tmp_path / "plan.json").write_text(json.dumps({"sections": sections}), encoding="utf-8")


@pytest.mark.asyncio
async def test_handle_plan_idle_emits_plan_ready(tmp_path):
    """Valid plan.json in planning stage → plan.ready emitted with sections."""
    orch, sm, bus, client = _make_orchestrator_planning(tmp_path)
    _write_valid_plan_json(tmp_path, num_sections=3)

    sub = bus.subscribe()
    await orch._handle_plan_idle()

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "plan.ready", f"Expected plan.ready; got {event['type']!r}"
    assert "sections" in event
    assert len(event["sections"]) == 3


@pytest.mark.asyncio
async def test_handle_plan_idle_updates_state(tmp_path):
    """Valid plan.json → state_manager updated with plan sections."""
    orch, sm, bus, client = _make_orchestrator_planning(tmp_path)
    _write_valid_plan_json(tmp_path, num_sections=4)

    await orch._handle_plan_idle()

    state = sm.get_state()
    assert "plan" in state
    assert len(state["plan"]) == 4


@pytest.mark.asyncio
async def test_handle_plan_idle_injects_proposed_status(tmp_path):
    """Each section in the plan gets status='proposed' injected by the orchestrator.

    N2-S03: initial section status is 'proposed' (plan proposed to user for
    review), not 'queued' (which is the status after plan acceptance, pre-build).
    """
    orch, sm, bus, client = _make_orchestrator_planning(tmp_path)
    _write_valid_plan_json(tmp_path, num_sections=3)

    await orch._handle_plan_idle()

    state = sm.get_state()
    for section in state["plan"]:
        assert section.get("status") == "proposed", f"Section missing status=proposed: {section}"


@pytest.mark.asyncio
async def test_handle_plan_idle_max_sections_six(tmp_path):
    """plan.json with exactly 6 sections → plan.ready emitted successfully."""
    orch, sm, bus, client = _make_orchestrator_planning(tmp_path)
    _write_valid_plan_json(tmp_path, num_sections=6)

    sub = bus.subscribe()
    await orch._handle_plan_idle()

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "plan.ready"
    assert len(event["sections"]) == 6


@pytest.mark.asyncio
async def test_handle_plan_idle_missing_plan_json_emits_turn_error(tmp_path):
    """Missing plan.json in planning stage → turn.error emitted."""
    orch, sm, bus, client = _make_orchestrator_planning(tmp_path)
    # Do NOT write plan.json.

    sub = bus.subscribe()
    await orch._handle_plan_idle()

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "turn.error", f"Expected turn.error; got {event['type']!r}"


@pytest.mark.asyncio
async def test_handle_plan_idle_invalid_json_emits_turn_error(tmp_path):
    """Malformed JSON in plan.json → turn.error emitted."""
    orch, sm, bus, client = _make_orchestrator_planning(tmp_path)
    (tmp_path / "plan.json").write_text("{not valid json", encoding="utf-8")

    sub = bus.subscribe()
    await orch._handle_plan_idle()

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "turn.error"


@pytest.mark.asyncio
async def test_handle_plan_idle_too_few_sections_emits_turn_error(tmp_path):
    """plan.json with < 3 sections → turn.error emitted."""
    import json

    orch, sm, bus, client = _make_orchestrator_planning(tmp_path)
    sections = [{"id": "sec_01", "title": "T1", "hypothesis": "H1"}]  # only 1 section
    (tmp_path / "plan.json").write_text(json.dumps({"sections": sections}), encoding="utf-8")

    sub = bus.subscribe()
    await orch._handle_plan_idle()

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "turn.error"


@pytest.mark.asyncio
async def test_handle_plan_idle_too_many_sections_emits_turn_error(tmp_path):
    """plan.json with > 6 sections → turn.error emitted."""
    orch, sm, bus, client = _make_orchestrator_planning(tmp_path)
    _write_valid_plan_json(tmp_path, num_sections=7)

    sub = bus.subscribe()
    await orch._handle_plan_idle()

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "turn.error"


@pytest.mark.asyncio
async def test_handle_plan_idle_missing_hypothesis_emits_turn_error(tmp_path):
    """Section missing 'hypothesis' field → turn.error emitted."""
    import json

    orch, sm, bus, client = _make_orchestrator_planning(tmp_path)
    sections = [
        {"id": "sec_01", "title": "T1", "hypothesis": "H1"},
        {"id": "sec_02", "title": "T2"},  # missing hypothesis
        {"id": "sec_03", "title": "T3", "hypothesis": "H3"},
    ]
    (tmp_path / "plan.json").write_text(json.dumps({"sections": sections}), encoding="utf-8")

    sub = bus.subscribe()
    await orch._handle_plan_idle()

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "turn.error"


@pytest.mark.asyncio
async def test_handle_plan_idle_null_sections_emits_turn_error(tmp_path):
    """plan.json with null sections field → turn.error emitted."""
    import json

    orch, sm, bus, client = _make_orchestrator_planning(tmp_path)
    (tmp_path / "plan.json").write_text(json.dumps({"sections": None}), encoding="utf-8")

    sub = bus.subscribe()
    await orch._handle_plan_idle()

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "turn.error"


@pytest.mark.asyncio
async def test_handle_plan_idle_wrong_stage_returns_early(tmp_path):
    """_handle_plan_idle when stage is not planning → no-op."""
    sm = _make_state_manager(tmp_path, session_id="sess-abc")
    sm.update(stage="profiling")
    bus = EventBus()
    mock_client = AsyncMock()
    orch = Orchestrator(state_manager=sm, bus=bus, client=mock_client, workspace_root=tmp_path)

    # Write a valid plan.json anyway.
    _write_valid_plan_json(tmp_path, num_sections=3)

    sub = bus.subscribe()
    await orch._handle_plan_idle()

    # No event should have been emitted.
    assert sub._queue.empty(), "No events should be emitted when stage != planning"


@pytest.mark.asyncio
async def test_plan_turn_calls_watchdog_if_wired(tmp_path):
    """_handle_planning_transition arms the watchdog before firing the plan turn."""
    from unittest.mock import MagicMock

    sm = _make_state_manager(tmp_path, session_id="sess-abc")
    sm.update(stage="profiling")
    bus = EventBus()
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(return_value=None)
    watchdog = MagicMock()
    watchdog.start_turn = MagicMock()
    orch = Orchestrator(state_manager=sm, bus=bus, client=mock_client, watchdog=watchdog)

    await orch._handle_planning_transition()
    await asyncio.sleep(0)

    watchdog.start_turn.assert_called_once()


@pytest.mark.asyncio
async def test_bus_listener_does_not_auto_advance_on_profile_ready(tmp_path):
    """profile.ready on bus must NOT auto-advance to planning.

    The transition is now gated on explicit user acceptance via
    POST /profile/accept → orchestrator.accept_profile().
    """
    sm = _make_state_manager(tmp_path, session_id="sess-abc")
    sm.update(stage="profiling", dataset="data.csv", aim="find patterns")
    bus = EventBus()
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(return_value=None)
    orch = Orchestrator(state_manager=sm, bus=bus, client=mock_client, workspace_root=tmp_path)

    sub = bus.subscribe()

    listener_task = asyncio.create_task(orch.start_bus_listener())
    await asyncio.sleep(0)

    await bus.publish("profile.ready", {"profile": {}, "ts": 12345})

    # Drain events briefly — no stage.changed should arrive.
    received = []
    try:
        for _ in range(3):
            event = await asyncio.wait_for(sub.__anext__(), timeout=0.3)
            received.append(event)
    except asyncio.TimeoutError:
        pass

    listener_task.cancel()
    try:
        await listener_task
    except asyncio.CancelledError:
        pass

    types = [e["type"] for e in received]
    assert "stage.changed" not in types, (
        f"profile.ready must NOT auto-advance to planning; got events: {types}"
    )
    assert sm.get_state()["stage"] == "profiling", (
        "Stage must remain 'profiling' until user accepts"
    )


@pytest.mark.asyncio
async def test_accept_profile_transitions_to_planning(tmp_path):
    """accept_profile() persists stage=planning and emits stage.changed."""
    sm = _make_state_manager(tmp_path, session_id="sess-abc")
    sm.update(stage="profiling", dataset="data.csv", aim="find patterns")
    bus = EventBus()
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(return_value=None)
    orch = Orchestrator(state_manager=sm, bus=bus, client=mock_client, workspace_root=tmp_path)

    sub = bus.subscribe()

    await orch.accept_profile()
    await asyncio.sleep(0)

    received = []
    try:
        for _ in range(3):
            event = await asyncio.wait_for(sub.__anext__(), timeout=0.5)
            received.append(event)
    except asyncio.TimeoutError:
        pass

    assert sm.get_state()["stage"] == "planning"
    types = [e["type"] for e in received]
    assert "stage.changed" in types, f"Expected stage.changed; got {types}"


@pytest.mark.asyncio
async def test_session_idle_stage_aware_dispatch_profiling(tmp_path):
    """session.idle in profiling stage dispatches to _handle_profile_idle, not plan handler."""
    import json

    sm = _make_state_manager(tmp_path, session_id="sess-abc")
    sm.update(stage="profiling")
    bus = EventBus()
    mock_client = AsyncMock()
    orch = Orchestrator(state_manager=sm, bus=bus, client=mock_client, workspace_root=tmp_path)

    profile_data = {
        "shape": {"rows": 10, "columns": 2},
        "columns": [{"name": "x", "type": "numeric", "flags": [], "summary": "col x"}],
        "flags": [],
    }
    (tmp_path / "profile.json").write_text(json.dumps(profile_data), encoding="utf-8")

    sub = bus.subscribe()
    listener_task = asyncio.create_task(orch.start_bus_listener())
    await asyncio.sleep(0)

    await bus.publish("session.idle", {"ts": 100})

    received = []
    try:
        for _ in range(3):
            event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
            received.append(event)
    except asyncio.TimeoutError:
        pass

    listener_task.cancel()
    try:
        await listener_task
    except asyncio.CancelledError:
        pass

    types = [e["type"] for e in received]
    # session.idle in profiling → should emit profile.ready (not plan.ready or turn.error)
    assert "profile.ready" in types, f"Expected profile.ready; got {types}"
    assert "plan.ready" not in types, f"plan.ready must not fire in profiling stage; got {types}"


@pytest.mark.asyncio
async def test_session_idle_stage_aware_dispatch_planning(tmp_path):
    """session.idle in planning stage dispatches to _handle_plan_idle, not profile handler."""
    orch, sm, bus, client = _make_orchestrator_planning(tmp_path)
    _write_valid_plan_json(tmp_path, num_sections=3)

    sub = bus.subscribe()
    listener_task = asyncio.create_task(orch.start_bus_listener())
    await asyncio.sleep(0)

    await bus.publish("session.idle", {"ts": 200})

    received = []
    try:
        for _ in range(3):
            event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
            received.append(event)
    except asyncio.TimeoutError:
        pass

    listener_task.cancel()
    try:
        await listener_task
    except asyncio.CancelledError:
        pass

    types = [e["type"] for e in received]
    # session.idle in planning → should emit plan.ready (not profile.ready)
    assert "plan.ready" in types, f"Expected plan.ready; got {types}"
    assert "profile.ready" not in types, (
        f"profile.ready must not fire in planning stage; got {types}"
    )


@pytest.mark.asyncio
async def test_section_build_uses_extended_watchdog_timeout(tmp_path):
    """start_build_section() calls watchdog.start_turn(timeout=180), not the default 60s."""
    from unittest.mock import MagicMock

    from backend.core.orchestrator import _SECTION_WATCHDOG_TIMEOUT

    sm = _make_state_manager(tmp_path, session_id="sess-abc")
    sm.update(stage="building", dataset="data.csv", aim="find patterns")
    bus = EventBus()
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(return_value=None)
    watchdog = MagicMock()
    watchdog.start_turn = MagicMock()
    orch = Orchestrator(
        state_manager=sm, bus=bus, client=mock_client, watchdog=watchdog, workspace_root=tmp_path
    )

    await orch.start_build_section(
        section_id="sec_01",
        section_index=1,
        title="Churn drivers",
        hypothesis="Age predicts churn",
        profile={},
    )
    await asyncio.sleep(0)

    watchdog.start_turn.assert_called_once_with(timeout=_SECTION_WATCHDOG_TIMEOUT)
    assert _SECTION_WATCHDOG_TIMEOUT == 180


# ---------------------------------------------------------------------------
# Section path persistence tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_ready_initialises_section_paths_to_null(tmp_path):
    """Sections stored in state after plan.ready have py/png/md_path = None."""
    orch, sm, bus, client = _make_orchestrator_planning(tmp_path)
    _write_valid_plan_json(tmp_path, num_sections=3)

    await orch._handle_plan_idle()

    state = sm.get_state()
    for section in state["plan"]:
        assert section.get("py_path") is None, f"Expected py_path=None: {section}"
        assert section.get("png_path") is None, f"Expected png_path=None: {section}"
        assert section.get("md_path") is None, f"Expected md_path=None: {section}"


@pytest.mark.asyncio
async def test_start_build_section_persists_status_building(tmp_path):
    """start_build_section() updates state.json section status to 'building'."""
    sm = _make_state_manager(tmp_path, session_id="sess-abc")
    sm.update(
        stage="building",
        dataset="data.csv",
        aim="find patterns",
        plan=[
            {
                "id": "sec_01",
                "title": "Churn",
                "hypothesis": "Age predicts",
                "status": "queued",
                "py_path": None,
                "png_path": None,
                "md_path": None,
            },
        ],
    )
    bus = EventBus()
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(return_value=None)
    orch = Orchestrator(state_manager=sm, bus=bus, client=mock_client, workspace_root=tmp_path)

    await orch.start_build_section(
        section_id="sec_01",
        section_index=1,
        title="Churn",
        hypothesis="Age predicts",
        profile={},
    )
    await asyncio.sleep(0)

    state = sm.get_state()
    section = next(s for s in state["plan"] if s["id"] == "sec_01")
    assert section["status"] == "building"


@pytest.mark.asyncio
async def test_handle_section_idle_persists_paths_to_state(tmp_path):
    """_handle_section_idle() stores py/png/md paths in state.json on section.proposed."""
    sm = _make_state_manager(tmp_path, session_id="sess-abc")
    slug = "churn_drivers"
    sm.update(
        stage="building",
        dataset="data.csv",
        aim="find churn",
        plan=[
            {
                "id": "sec_01",
                "title": "Churn Drivers",
                "hypothesis": "H",
                "status": "building",
                "slug": slug,
                "index": 1,
                "py_path": None,
                "png_path": None,
                "md_path": None,
            }
        ],
    )
    bus = EventBus()
    mock_client = AsyncMock()
    orch = Orchestrator(state_manager=sm, bus=bus, client=mock_client, workspace_root=tmp_path)

    # Write the expected artefact files.
    base = f"sec_01_{slug}"
    (tmp_path / "analyses").mkdir(parents=True, exist_ok=True)
    (tmp_path / "charts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "sections").mkdir(parents=True, exist_ok=True)
    (tmp_path / "analyses" / f"{base}.py").write_text("print('hi')", encoding="utf-8")
    (tmp_path / "charts" / f"{base}.png").write_bytes(b"\x89PNG")
    (tmp_path / "sections" / f"{base}.md").write_text("# Result", encoding="utf-8")

    await orch._handle_section_idle()

    state = sm.get_state()
    section = next(s for s in state["plan"] if s["id"] == "sec_01")
    assert section["status"] == "proposed"
    assert section["py_path"] == f"analyses/{base}.py"
    assert section["png_path"] == f"charts/{base}.png"
    assert section["md_path"] == f"sections/{base}.md"


@pytest.mark.asyncio
async def test_handle_section_idle_persists_failed_status(tmp_path):
    """_handle_section_idle() stores status=failed in state.json when artefacts are missing."""
    sm = _make_state_manager(tmp_path, session_id="sess-abc")
    sm.update(
        stage="building",
        dataset="data.csv",
        aim="find churn",
        plan=[
            {
                "id": "sec_01",
                "title": "Churn Drivers",
                "hypothesis": "H",
                "status": "building",
                "slug": "churn_drivers",
                "index": 1,
                "py_path": None,
                "png_path": None,
                "md_path": None,
            }
        ],
    )
    bus = EventBus()
    mock_client = AsyncMock()
    orch = Orchestrator(state_manager=sm, bus=bus, client=mock_client, workspace_root=tmp_path)
    # Do NOT create artefact files — forces section.failed path.

    await orch._handle_section_idle()

    state = sm.get_state()
    section = next(s for s in state["plan"] if s["id"] == "sec_01")
    assert section["status"] == "failed"


# ---------------------------------------------------------------------------
# Watchdog cancel + auto-sequencing tests
# ---------------------------------------------------------------------------


def _make_two_section_plan(building_slug: str) -> list[dict]:
    """Return a plan where sec_01 is building and sec_02 is queued."""
    return [
        {
            "id": "sec_01",
            "title": "First",
            "hypothesis": "H1",
            "status": "building",
            "slug": building_slug,
            "index": 1,
            "py_path": None,
            "png_path": None,
            "md_path": None,
        },
        {
            "id": "sec_02",
            "title": "Second",
            "hypothesis": "H2",
            "status": "queued",
            "py_path": None,
            "png_path": None,
            "md_path": None,
        },
    ]


@pytest.mark.asyncio
async def test_section_idle_cancels_watchdog_on_completion(tmp_path):
    """_handle_section_idle() cancels the watchdog when a section completes."""
    from unittest.mock import MagicMock

    slug = "first"
    sm = _make_state_manager(tmp_path, session_id="sess-abc")
    sm.update(stage="building", dataset="d.csv", aim="a", plan=_make_two_section_plan(slug))
    bus = EventBus()
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(return_value=None)
    watchdog = MagicMock()
    watchdog.cancel = MagicMock()
    watchdog.start_turn = MagicMock()
    orch = Orchestrator(
        state_manager=sm, bus=bus, client=mock_client, watchdog=watchdog, workspace_root=tmp_path
    )

    # Write artefacts for sec_01 so section.proposed fires.
    base = f"sec_01_{slug}"
    for d in ("analyses", "charts", "sections"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    (tmp_path / "analyses" / f"{base}.py").write_text("x", encoding="utf-8")
    (tmp_path / "charts" / f"{base}.png").write_bytes(b"\x89PNG")
    (tmp_path / "sections" / f"{base}.md").write_text("# R", encoding="utf-8")

    await orch._handle_section_idle()
    await asyncio.sleep(0)

    watchdog.cancel.assert_called_once()


@pytest.mark.asyncio
async def test_section_idle_auto_starts_next_queued_section(tmp_path):
    """_handle_section_idle() starts the next queued section after section.proposed."""
    slug = "first"
    sm = _make_state_manager(tmp_path, session_id="sess-abc")
    sm.update(stage="building", dataset="d.csv", aim="a", plan=_make_two_section_plan(slug))
    bus = EventBus()
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(return_value=None)
    orch = Orchestrator(state_manager=sm, bus=bus, client=mock_client, workspace_root=tmp_path)

    base = f"sec_01_{slug}"
    for d in ("analyses", "charts", "sections"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    (tmp_path / "analyses" / f"{base}.py").write_text("x", encoding="utf-8")
    (tmp_path / "charts" / f"{base}.png").write_bytes(b"\x89PNG")
    (tmp_path / "sections" / f"{base}.md").write_text("# R", encoding="utf-8")

    await orch._handle_section_idle()
    await asyncio.sleep(0)

    state = sm.get_state()
    sec2 = next(s for s in state["plan"] if s["id"] == "sec_02")
    assert sec2["status"] == "building"
    # client.prompt must have been called for the new section turn.
    mock_client.prompt.assert_awaited_once()


@pytest.mark.asyncio
async def test_section_idle_no_more_sections_does_not_start_turn(tmp_path):
    """_handle_section_idle() with no queued sections left does not call client.prompt."""
    slug = "only"
    sm = _make_state_manager(tmp_path, session_id="sess-abc")
    sm.update(
        stage="building",
        dataset="d.csv",
        aim="a",
        plan=[
            {
                "id": "sec_01",
                "title": "Only",
                "hypothesis": "H",
                "status": "building",
                "slug": slug,
                "index": 1,
                "py_path": None,
                "png_path": None,
                "md_path": None,
            }
        ],
    )
    bus = EventBus()
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(return_value=None)
    orch = Orchestrator(state_manager=sm, bus=bus, client=mock_client, workspace_root=tmp_path)

    base = f"sec_01_{slug}"
    for d in ("analyses", "charts", "sections"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    (tmp_path / "analyses" / f"{base}.py").write_text("x", encoding="utf-8")
    (tmp_path / "charts" / f"{base}.png").write_bytes(b"\x89PNG")
    (tmp_path / "sections" / f"{base}.md").write_text("# R", encoding="utf-8")

    await orch._handle_section_idle()
    await asyncio.sleep(0)

    mock_client.prompt.assert_not_awaited()


@pytest.mark.asyncio
async def test_accept_plan_transitions_sections_to_queued(tmp_path):
    """accept_plan() changes all 'proposed' sections to 'queued' status."""
    sm = _make_state_manager(tmp_path, session_id="sess-abc")
    sm.update(
        stage="planning",
        dataset="d.csv",
        aim="a",
        plan=[
            {
                "id": "sec_01",
                "title": "S1",
                "hypothesis": "H1",
                "status": "proposed",
                "py_path": None,
                "png_path": None,
                "md_path": None,
            },
            {
                "id": "sec_02",
                "title": "S2",
                "hypothesis": "H2",
                "status": "proposed",
                "py_path": None,
                "png_path": None,
                "md_path": None,
            },
        ],
    )
    bus = EventBus()
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(return_value=None)
    orch = Orchestrator(state_manager=sm, bus=bus, client=mock_client, workspace_root=tmp_path)

    await orch.accept_plan()
    await asyncio.sleep(0)

    state = sm.get_state()
    # sec_01 must be "building" — start_build_section persists that status.
    sec1 = next(s for s in state["plan"] if s["id"] == "sec_01")
    assert sec1["status"] == "building"
    # sec_02 remains queued until sec_01 completes.
    sec2 = next(s for s in state["plan"] if s["id"] == "sec_02")
    assert sec2["status"] == "queued"


# ---------------------------------------------------------------------------
# N3-S02: retry_last_turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_last_turn_replays_profile_prompt(tmp_path):
    """retry_last_turn() replays the last profiling prompt to the same session.

    After _run_profile_turn records _last_turn, retry_last_turn() must call
    client.prompt with the same prompt text.
    """
    orch, sm, bus, client = _make_orchestrator(tmp_path)
    sm.update(stage="profiling", dataset="data.csv", aim="find patterns")

    # Simulate a prior profile turn by directly setting _last_turn.
    orch._last_turn = {
        "stage": "profiling",
        "prompt": "Profile the dataset",
        "section_id": None,
        "retries": 0,
    }

    client.prompt.reset_mock()
    await orch.retry_last_turn()
    await asyncio.sleep(0)

    client.prompt.assert_awaited_once()
    args, _ = client.prompt.call_args
    assert args[0] == "sess-abc", f"Expected session_id 'sess-abc', got {args[0]!r}"
    assert args[1] == "Profile the dataset"


@pytest.mark.asyncio
async def test_retry_last_turn_uses_fresh_session(tmp_path):
    """retry_last_turn() reads the session ID fresh from state after a watchdog swap.

    After a watchdog session swap, the session ID in state.json changes.
    retry_last_turn() must target the new session, not a stale reference.
    """
    orch, sm, bus, client = _make_orchestrator(tmp_path)
    sm.update(stage="profiling", dataset="data.csv", aim="find patterns")

    orch._last_turn = {
        "stage": "profiling",
        "prompt": "Profile the dataset",
        "section_id": None,
        "retries": 0,
    }

    # Simulate watchdog session swap: new session ID persisted to state.
    sm.update(opencode_session_id="sess-new-456")
    client.prompt.reset_mock()

    await orch.retry_last_turn()
    await asyncio.sleep(0)

    client.prompt.assert_awaited_once()
    args, _ = client.prompt.call_args
    assert args[0] == "sess-new-456", f"Expected fresh session_id 'sess-new-456', got {args[0]!r}"


@pytest.mark.asyncio
async def test_retry_bounded_at_three(tmp_path):
    """retry_last_turn() emits turn.error with retryable=False after 3 retries.

    On the 4th retry attempt (retries >= 3), no further client.prompt is called;
    turn.error is emitted with retryable=False.
    """
    orch, sm, bus, client = _make_orchestrator(tmp_path)
    sm.update(stage="profiling", dataset="data.csv", aim="find patterns")

    orch._last_turn = {
        "stage": "profiling",
        "prompt": "Profile the dataset",
        "section_id": None,
        "retries": 3,  # Already at the limit.
    }

    sub = bus.subscribe()
    client.prompt.reset_mock()

    await orch.retry_last_turn()
    await asyncio.sleep(0)

    # No further prompt call.
    client.prompt.assert_not_awaited()

    # turn.error must be emitted with retryable=False.
    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "turn.error", f"Expected turn.error; got {event['type']!r}"
    assert event.get("retryable") is False, (
        f"Expected retryable=False; got {event.get('retryable')!r}"
    )


@pytest.mark.asyncio
async def test_retry_without_prior_turn(tmp_path):
    """retry_last_turn() with no prior turn is a no-op — no error, no crash, no prompt.

    When _last_turn is None, retry silently returns without emitting anything or
    calling client.prompt.
    """
    orch, sm, bus, client = _make_orchestrator(tmp_path)
    sm.update(stage="profiling", dataset="data.csv", aim="find patterns")

    # Ensure _last_turn is None.
    orch._last_turn = None
    client.prompt.reset_mock()

    sub = bus.subscribe()
    await orch.retry_last_turn()
    await asyncio.sleep(0)

    client.prompt.assert_not_awaited()
    assert sub._queue.empty(), "No events should be emitted when there is no last turn"


# ---------------------------------------------------------------------------
# N3-S03: turn.error payload includes stage and retryable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_turn_error_has_stage_and_retryable(tmp_path):
    """_run_profile_turn emits turn.error with stage='profiling' and retryable=True on failure.

    Acceptance (N3-S03): structured-output failures and provider errors emit
    turn.error with stage/section_id/retryable fields per the API contract.
    """
    sm = _make_state_manager(tmp_path, session_id="sess-abc")
    sm.update(stage="profiling")
    bus = EventBus()
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(side_effect=RuntimeError("provider error"))
    orch = Orchestrator(state_manager=sm, bus=bus, client=mock_client, workspace_root=tmp_path)

    sub = bus.subscribe()

    await orch._run_profile_turn("sess-abc", "Profile the data")
    await asyncio.sleep(0)

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "turn.error", f"Expected turn.error; got {event['type']!r}"
    assert event.get("stage") == "profiling", (
        f"Expected stage='profiling'; got {event.get('stage')!r}"
    )
    assert event.get("retryable") is True, (
        f"Expected retryable=True; got {event.get('retryable')!r}"
    )
    assert "message" in event, "turn.error must include message field"


@pytest.mark.asyncio
async def test_turn_error_planning_has_stage(tmp_path):
    """_run_plan_turn emits turn.error with stage='planning' on failure."""
    sm = _make_state_manager(tmp_path, session_id="sess-abc")
    sm.update(stage="planning")
    bus = EventBus()
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(side_effect=RuntimeError("plan error"))
    orch = Orchestrator(state_manager=sm, bus=bus, client=mock_client, workspace_root=tmp_path)

    sub = bus.subscribe()

    await orch._run_plan_turn("sess-abc", "Draft the plan")
    await asyncio.sleep(0)

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "turn.error"
    assert event.get("stage") == "planning"
    assert event.get("retryable") is True


@pytest.mark.asyncio
async def test_turn_error_building_has_stage_and_section_id(tmp_path):
    """_run_section_turn emits turn.error with stage='building' and section_id on failure."""
    sm = _make_state_manager(tmp_path, session_id="sess-abc")
    sm.update(stage="building")
    bus = EventBus()
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(side_effect=RuntimeError("section build error"))
    orch = Orchestrator(state_manager=sm, bus=bus, client=mock_client, workspace_root=tmp_path)

    sub = bus.subscribe()

    await orch._run_section_turn("sess-abc", "Build the section", section_id="sec_01")
    await asyncio.sleep(0)

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "turn.error"
    assert event.get("stage") == "building"
    assert event.get("section_id") == "sec_01"
    assert event.get("retryable") is True


# ---------------------------------------------------------------------------
# N3-S16: QA_FORCE_TURN_ERROR seam
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_qa_force_turn_error(tmp_path, monkeypatch):
    """With QA_FORCE_TURN_ERROR=1, client.prompt raises and turn.error is emitted.

    Acceptance (N3-S16): when the env var is set, the prompt raises before any
    OpenCode traffic occurs, and turn.error fires via the existing exception handler.
    """
    monkeypatch.setenv("QA_FORCE_TURN_ERROR", "1")

    sm = _make_state_manager(tmp_path, session_id="sess-abc")
    sm.update(stage="profiling")
    bus = EventBus()
    mock_client = AsyncMock()
    # prompt should NOT be called because the seam raises first
    mock_client.prompt = AsyncMock(return_value=None)
    orch = Orchestrator(state_manager=sm, bus=bus, client=mock_client, workspace_root=tmp_path)

    sub = bus.subscribe()

    await orch._run_profile_turn("sess-abc", "Profile the data")
    await asyncio.sleep(0)

    # turn.error must be emitted.
    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "turn.error", f"Expected turn.error; got {event['type']!r}"
    assert event.get("stage") == "profiling"
    assert event.get("retryable") is True
    # The seam fires before client.prompt — so prompt should not have been awaited.
    mock_client.prompt.assert_not_awaited()


# ---------------------------------------------------------------------------
# N3-S01: _check_done_or_next — done transition and sequencing
# ---------------------------------------------------------------------------


def _make_building_orchestrator(
    tmp_path: Path,
    *,
    plan: list[dict],
    session_id: str | None = "sess-abc",
) -> tuple[Orchestrator, StateManager, EventBus, AsyncMock]:
    """Return an Orchestrator pre-set to building stage with the given plan."""
    sm = _make_state_manager(tmp_path, session_id=session_id)
    sm.update(stage="building", dataset="d.csv", aim="a", plan=plan)
    bus = EventBus()
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(return_value=None)
    orch = Orchestrator(state_manager=sm, bus=bus, client=mock_client, workspace_root=tmp_path)
    return orch, sm, bus, mock_client


def _all_accepted_plan() -> list[dict]:
    return [
        {
            "id": "sec_01",
            "title": "S1",
            "hypothesis": "H1",
            "status": "accepted",
            "py_path": None,
            "png_path": None,
            "md_path": None,
        },
        {
            "id": "sec_02",
            "title": "S2",
            "hypothesis": "H2",
            "status": "accepted",
            "py_path": None,
            "png_path": None,
            "md_path": None,
        },
    ]


@pytest.mark.asyncio
async def test_done_transition_when_all_accepted(tmp_path):
    """_check_done_or_next: all sections accepted → stage=done, stage.changed(done) emitted.

    N3-S01 acceptance: Given the last section is accepted, when the loop runs,
    then stage transitions to done and stage.changed(done) is emitted.
    """
    orch, sm, bus, client = _make_building_orchestrator(tmp_path, plan=_all_accepted_plan())
    sub = bus.subscribe()

    await orch._check_done_or_next("sec_02")

    # Stage persisted as done.
    assert sm.get_state()["stage"] == "done", "Stage must be 'done' when all sections accepted"

    # stage.changed(done) emitted.
    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "stage.changed", f"Expected stage.changed; got {event['type']!r}"
    assert event.get("stage") == "done", f"Expected stage=done; got {event.get('stage')!r}"


@pytest.mark.asyncio
async def test_done_transition_when_mixed_accepted_dropped(tmp_path):
    """_check_done_or_next: mix of accepted and dropped (no queued/building) → done.

    N3-S01 acceptance: Given dropped sections, when sequencing, then they are skipped
    (already handled by queued status) and done is emitted when all are terminal.
    """
    plan = [
        {
            "id": "sec_01",
            "title": "S1",
            "hypothesis": "H1",
            "status": "accepted",
            "py_path": None,
            "png_path": None,
            "md_path": None,
        },
        {
            "id": "sec_02",
            "title": "S2",
            "hypothesis": "H2",
            "status": "dropped",
            "py_path": None,
            "png_path": None,
            "md_path": None,
        },
        {
            "id": "sec_03",
            "title": "S3",
            "hypothesis": "H3",
            "status": "failed",
            "py_path": None,
            "png_path": None,
            "md_path": None,
        },
    ]
    orch, sm, bus, client = _make_building_orchestrator(tmp_path, plan=plan)
    sub = bus.subscribe()

    await orch._check_done_or_next("sec_03")

    assert sm.get_state()["stage"] == "done"
    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "stage.changed"
    assert event.get("stage") == "done"


@pytest.mark.asyncio
async def test_no_done_while_section_still_queued(tmp_path):
    """_check_done_or_next: a queued section still remains → no done transition.

    N3-S01 acceptance: auto-sequence is still running; done must not fire prematurely.
    """
    plan = [
        {
            "id": "sec_01",
            "title": "S1",
            "hypothesis": "H1",
            "status": "accepted",
            "py_path": None,
            "png_path": None,
            "md_path": None,
        },
        {
            "id": "sec_02",
            "title": "S2",
            "hypothesis": "H2",
            "status": "queued",
            "py_path": None,
            "png_path": None,
            "md_path": None,
        },
    ]
    orch, sm, bus, client = _make_building_orchestrator(tmp_path, plan=plan)
    sub = bus.subscribe()

    await orch._check_done_or_next("sec_01")

    # Stage must remain building.
    assert sm.get_state()["stage"] == "building", (
        "Stage must remain 'building' while sections are queued"
    )
    # No event emitted.
    assert sub._queue.empty(), "No stage.changed must be emitted while a section is queued"


@pytest.mark.asyncio
async def test_no_done_while_section_still_building(tmp_path):
    """_check_done_or_next: a section is still building → no done transition."""
    plan = [
        {
            "id": "sec_01",
            "title": "S1",
            "hypothesis": "H1",
            "status": "accepted",
            "py_path": None,
            "png_path": None,
            "md_path": None,
        },
        {
            "id": "sec_02",
            "title": "S2",
            "hypothesis": "H2",
            "status": "building",
            "py_path": None,
            "png_path": None,
            "md_path": None,
        },
    ]
    orch, sm, bus, client = _make_building_orchestrator(tmp_path, plan=plan)
    sub = bus.subscribe()

    await orch._check_done_or_next("sec_01")

    assert sm.get_state()["stage"] == "building", (
        "Stage must remain 'building' while a section is building"
    )
    assert sub._queue.empty(), "No stage.changed must be emitted while a section is building"


@pytest.mark.asyncio
async def test_rapid_accept_safety(tmp_path):
    """Two rapid _check_done_or_next calls do not double-emit stage.changed(done).

    N3-S01 acceptance: Given rapid accepts, when they occur, the loop is re-entrant safe.
    """
    orch, sm, bus, client = _make_building_orchestrator(tmp_path, plan=_all_accepted_plan())
    sub = bus.subscribe()

    # Call twice (simulating rapid accepts / race).
    await orch._check_done_or_next("sec_02")
    await orch._check_done_or_next("sec_02")

    # Collect all events.
    received = []
    try:
        for _ in range(5):
            event = await asyncio.wait_for(sub.__anext__(), timeout=0.2)
            received.append(event)
    except asyncio.TimeoutError:
        pass

    # stage.changed(done) must be emitted exactly once.
    done_events = [
        e for e in received if e.get("type") == "stage.changed" and e.get("stage") == "done"
    ]
    assert len(done_events) == 1, (
        f"Expected exactly 1 stage.changed(done) event; got {len(done_events)}: {received}"
    )


@pytest.mark.asyncio
async def test_check_done_noop_when_not_building(tmp_path):
    """_check_done_or_next is a no-op when the current stage is not 'building'."""
    sm = _make_state_manager(tmp_path, session_id="sess-abc")
    sm.update(stage="planning", plan=_all_accepted_plan())
    bus = EventBus()
    mock_client = AsyncMock()
    orch = Orchestrator(state_manager=sm, bus=bus, client=mock_client, workspace_root=tmp_path)
    sub = bus.subscribe()

    await orch._check_done_or_next("sec_01")

    assert sm.get_state()["stage"] == "planning", "Stage must not change when not building"
    assert sub._queue.empty(), "No events emitted when stage is not building"


@pytest.mark.asyncio
async def test_start_next_queued_calls_check_done_when_no_queued(tmp_path):
    """_start_next_queued_section calls _check_done_or_next when no queued sections remain.

    Belt-and-suspenders fallback for the auto-sequence path: when all sections have been
    processed (proposed/failed/accepted) via session.idle, the loop still reaches done.
    """
    plan = [
        {
            "id": "sec_01",
            "title": "S1",
            "hypothesis": "H1",
            "status": "accepted",
            "py_path": None,
            "png_path": None,
            "md_path": None,
        },
    ]
    orch, sm, bus, client = _make_building_orchestrator(tmp_path, plan=plan)
    sub = bus.subscribe()

    # _start_next_queued_section with no queued sections should trigger _check_done_or_next.
    await orch._start_next_queued_section()

    # Since all sections are accepted and stage is building → done.
    assert sm.get_state()["stage"] == "done"
    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "stage.changed"
    assert event.get("stage") == "done"
