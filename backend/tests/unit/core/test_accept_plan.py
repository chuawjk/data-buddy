"""Unit tests for POST /plan/accept — N2-S05.

TDD: tests written before the implementation.

Acceptance criteria covered:
- POST /plan/accept → stage transitions planning→building.
- stage.changed event emitted with stage="building".
- client.prompt called with correct session_id and non-empty prompt (section 1 triggered).
- Watchdog armed on first call.
- Idempotent on repeat call (stage=building → no extra client.prompt call).
- No httpx import in orchestrator (architecture boundary).
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.event_bus import EventBus
from backend.core.orchestrator import Orchestrator
from backend.core.state_manager import StateManager

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_PLAN_WITH_PROPOSED = [
    {
        "id": "sec_01",
        "title": "Cohort overview",
        "hypothesis": "Establish churn rate",
        "status": "proposed",
    },
    {
        "id": "sec_02",
        "title": "Churn by tier",
        "hypothesis": "Tier drives churn",
        "status": "proposed",
    },
]


def _make_orchestrator(
    tmp_path: Path,
    *,
    session_id: str | None = "sess-abc",
    plan: list | None = None,
    stage: str = "planning",
) -> tuple[Orchestrator, StateManager, EventBus, AsyncMock]:
    """Return a fully-wired Orchestrator in the planning stage with a plan."""
    sm = StateManager(path=tmp_path / "state.json")
    sm.load()
    sm.update(
        stage=stage,
        opencode_session_id=session_id,
        plan=plan if plan is not None else list(_PLAN_WITH_PROPOSED),
        aim="Understand churn",
        dataset="data.csv",
        profile={"shape": {"rows": 100, "columns": 5}, "columns": [], "flags": []},
    )

    bus = EventBus()
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(return_value=None)

    orch = Orchestrator(
        state_manager=sm,
        bus=bus,
        client=mock_client,
        workspace_root=tmp_path,
    )
    return orch, sm, bus, mock_client


# ---------------------------------------------------------------------------
# Happy path — stage transitions to building
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_plan_transitions_stage_to_building(tmp_path: Path):
    """accept_plan() persists stage=building via state_manager.update()."""
    orch, sm, bus, client = _make_orchestrator(tmp_path)

    await orch.accept_plan()
    await asyncio.sleep(0)

    assert sm.get_state()["stage"] == "building"


@pytest.mark.asyncio
async def test_accept_plan_emits_stage_changed(tmp_path: Path):
    """accept_plan() publishes stage.changed with stage="building"."""
    orch, sm, bus, client = _make_orchestrator(tmp_path)
    sub = bus.subscribe()

    await orch.accept_plan()
    await asyncio.sleep(0)

    event = await sub.__anext__()
    assert event["type"] == "stage.changed"
    assert event.get("stage") == "building"


# ---------------------------------------------------------------------------
# Section build triggered via narrow client interface
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_plan_triggers_client_prompt(tmp_path: Path):
    """accept_plan() calls client.prompt(session_id, prompt_text, schema=None)."""
    orch, sm, bus, client = _make_orchestrator(tmp_path)

    await orch.accept_plan()
    await asyncio.sleep(0)

    client.prompt.assert_awaited_once()
    args, kwargs = client.prompt.call_args
    assert args[0] == "sess-abc", f"session_id must be 'sess-abc', got {args[0]!r}"
    prompt_text = args[1]
    assert isinstance(prompt_text, str) and len(prompt_text) > 0, "Prompt must be non-empty string"


@pytest.mark.asyncio
async def test_accept_plan_triggers_first_proposed_section(tmp_path: Path):
    """accept_plan() uses the first proposed section's details in the prompt."""
    orch, sm, bus, client = _make_orchestrator(tmp_path)

    await orch.accept_plan()
    await asyncio.sleep(0)

    args, kwargs = client.prompt.call_args
    prompt_text = args[1]
    # The first section title must appear in the prompt.
    assert "sec_01" in prompt_text or "Cohort overview" in prompt_text, (
        f"Prompt should reference first section; got: {prompt_text[:200]!r}"
    )


@pytest.mark.asyncio
async def test_accept_plan_prompt_schema_is_none(tmp_path: Path):
    """accept_plan() calls client.prompt with schema=None (ADR-005)."""
    orch, sm, bus, client = _make_orchestrator(tmp_path)

    await orch.accept_plan()
    await asyncio.sleep(0)

    args, kwargs = client.prompt.call_args
    schema = kwargs.get("schema", args[2] if len(args) > 2 else None)
    assert schema is None, f"Schema must be None for section prompts (ADR-005), got {schema!r}"


# ---------------------------------------------------------------------------
# Watchdog armed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_plan_arms_watchdog(tmp_path: Path):
    """accept_plan() calls watchdog.start_turn() before the section prompt."""
    sm = StateManager(path=tmp_path / "state.json")
    sm.load()
    sm.update(
        stage="planning",
        opencode_session_id="sess-abc",
        plan=list(_PLAN_WITH_PROPOSED),
        aim="Understand churn",
        dataset="data.csv",
        profile={"shape": {"rows": 100, "columns": 5}, "columns": [], "flags": []},
    )
    bus = EventBus()
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(return_value=None)
    mock_watchdog = MagicMock()

    orch = Orchestrator(
        state_manager=sm,
        bus=bus,
        client=mock_client,
        workspace_root=tmp_path,
        watchdog=mock_watchdog,
    )

    await orch.accept_plan()
    await asyncio.sleep(0)

    mock_watchdog.start_turn.assert_called_once()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_plan_idempotent_when_already_building(tmp_path: Path):
    """accept_plan() called when stage=building must not call client.prompt again."""
    orch, sm, bus, client = _make_orchestrator(tmp_path, stage="building")

    await orch.accept_plan()
    await asyncio.sleep(0)

    # Should not call client.prompt — already in building stage.
    client.prompt.assert_not_awaited()


@pytest.mark.asyncio
async def test_accept_plan_idempotent_stage_stays_building(tmp_path: Path):
    """accept_plan() called when already building must not change the stage."""
    orch, sm, bus, client = _make_orchestrator(tmp_path, stage="building")

    await orch.accept_plan()
    await asyncio.sleep(0)

    assert sm.get_state()["stage"] == "building"


@pytest.mark.asyncio
async def test_accept_plan_called_twice_only_one_prompt(tmp_path: Path):
    """accept_plan() called twice must only trigger one section prompt."""
    orch, sm, bus, client = _make_orchestrator(tmp_path)

    await orch.accept_plan()
    await asyncio.sleep(0)
    # Second call — state is now building, should be idempotent.
    await orch.accept_plan()
    await asyncio.sleep(0)

    assert client.prompt.await_count == 1, (
        f"client.prompt should be called exactly once; called {client.prompt.await_count} times"
    )


# ---------------------------------------------------------------------------
# Edge case — no session_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_plan_no_session_no_prompt(tmp_path: Path):
    """accept_plan() with no session_id transitions stage but does not call client.prompt."""
    orch, sm, bus, client = _make_orchestrator(tmp_path, session_id=None)

    await orch.accept_plan()
    await asyncio.sleep(0)

    # Stage should still transition.
    assert sm.get_state()["stage"] == "building"
    # But no prompt sent.
    client.prompt.assert_not_awaited()


# ---------------------------------------------------------------------------
# Edge case — empty plan
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_plan_empty_plan_no_prompt(tmp_path: Path):
    """accept_plan() with an empty plan transitions stage but does not call client.prompt."""
    orch, sm, bus, client = _make_orchestrator(tmp_path, plan=[])

    await orch.accept_plan()
    await asyncio.sleep(0)

    assert sm.get_state()["stage"] == "building"
    client.prompt.assert_not_awaited()


# ---------------------------------------------------------------------------
# Architecture constraint — no httpx import in orchestrator
# ---------------------------------------------------------------------------


def test_orchestrator_no_httpx_import():
    """orchestrator.py must not import httpx (architecture boundary check)."""
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
