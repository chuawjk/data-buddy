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
