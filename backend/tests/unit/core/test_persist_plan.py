"""Unit tests for N2-S03 — Persist plan & section statuses.

TDD: tests written before implementation.

Acceptance criteria covered:
- Given ``plan.ready``, when handled, then ``plan.json`` is written and each
  section is recorded with status ``proposed`` in state.json.
- Given the persisted plan, when ``GET /state`` is called, then it reflects the
  plan and statuses.
- Given the write, when performed, then atomic-write semantics are preserved.

Tests mirror ``backend/orchestrator.py`` → path
``backend/tests/unit/app/test_persist_plan.py``.
"""

from __future__ import annotations

import asyncio
import json
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


def _make_orchestrator_planning(
    tmp_path: Path,
    *,
    session_id: str | None = "sess-abc",
) -> tuple[Orchestrator, StateManager, EventBus, AsyncMock]:
    """Return a fully-wired Orchestrator pre-set to planning stage."""
    sm = _make_state_manager(tmp_path, session_id=session_id)
    sm.update(stage="planning", dataset="data.csv", aim="find patterns")
    bus = EventBus()
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(return_value=None)
    orch = Orchestrator(state_manager=sm, bus=bus, client=mock_client, workspace_root=tmp_path)
    return orch, sm, bus, mock_client


def _write_valid_plan_json(tmp_path: Path, num_sections: int = 3) -> None:
    """Write a valid plan.json (as OpenCode would produce it) to tmp_path."""
    sections = [
        {"id": f"sec_{i:02d}", "title": f"Section {i}", "hypothesis": f"Hypothesis {i}"}
        for i in range(1, num_sections + 1)
    ]
    (tmp_path / "plan.json").write_text(json.dumps({"sections": sections}), encoding="utf-8")


# ---------------------------------------------------------------------------
# Happy path: plan.ready → plan.json written + state.json sections proposed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_ready_writes_plan_json(tmp_path):
    """_handle_plan_idle() writes canonical plan.json to workspace.

    Acceptance: Given plan.ready, when handled, then plan.json is written.
    """
    orch, sm, bus, client = _make_orchestrator_planning(tmp_path)
    _write_valid_plan_json(tmp_path, num_sections=3)

    plan_path = tmp_path / "plan.json"

    await orch._handle_plan_idle()

    assert plan_path.exists(), "plan.json must be written by _handle_plan_idle()"
    content = json.loads(plan_path.read_text(encoding="utf-8"))
    assert "sections" in content, "plan.json must have a 'sections' key"
    assert len(content["sections"]) == 3


@pytest.mark.asyncio
async def test_plan_ready_sections_have_proposed_status(tmp_path):
    """Each section in state.json has status='proposed' after _handle_plan_idle().

    Acceptance: Given plan.ready, when handled, then each section is recorded
    with status 'proposed' in state.json.
    """
    orch, sm, bus, client = _make_orchestrator_planning(tmp_path)
    _write_valid_plan_json(tmp_path, num_sections=4)

    await orch._handle_plan_idle()

    state = sm.get_state()
    assert "plan" in state, "state must have a 'plan' key"
    assert len(state["plan"]) == 4, f"Expected 4 sections, got {len(state['plan'])}"
    for section in state["plan"]:
        assert section.get("status") == "proposed", (
            f"Expected status='proposed', got {section.get('status')!r} in section {section}"
        )


@pytest.mark.asyncio
async def test_get_state_reflects_plan_with_statuses(tmp_path):
    """After _handle_plan_idle(), get_state() returns plan with per-section statuses.

    Acceptance: Given the persisted plan, when GET /state is called, then it
    reflects the plan and statuses.

    Uses state_manager.get_state() as the proxy for GET /state (the router
    strips only internal fields; plan is returned verbatim).
    """
    orch, sm, bus, client = _make_orchestrator_planning(tmp_path)
    _write_valid_plan_json(tmp_path, num_sections=3)

    await orch._handle_plan_idle()

    # Simulate what GET /state returns.
    state = sm.get_state()
    plan = state.get("plan", [])

    assert isinstance(plan, list), "plan must be a list"
    assert len(plan) == 3
    # All required fields present on each section.
    for section in plan:
        assert "id" in section
        assert "title" in section
        assert "hypothesis" in section
        assert "status" in section
        assert section["status"] == "proposed"


@pytest.mark.asyncio
async def test_plan_json_written_atomically(tmp_path):
    """plan.json write uses atomic tmp+rename semantics.

    Acceptance: Given the write, when performed, then atomic-write semantics
    are preserved.

    We verify:
    - No tmp file remains after the write.
    - The final plan.json is valid JSON.
    - The tmp file path (plan.tmp.json) does not exist after the call.
    """
    orch, sm, bus, client = _make_orchestrator_planning(tmp_path)
    _write_valid_plan_json(tmp_path, num_sections=3)

    await orch._handle_plan_idle()

    plan_path = tmp_path / "plan.json"
    tmp_path_plan = tmp_path / "plan.tmp.json"

    # Final file exists and is valid JSON.
    assert plan_path.exists(), "plan.json must exist after _handle_plan_idle()"
    content = json.loads(plan_path.read_text(encoding="utf-8"))
    assert isinstance(content, dict), "plan.json must be a JSON object"

    # Tmp file cleaned up.
    assert not tmp_path_plan.exists(), "plan.tmp.json must not remain after atomic write"


# ---------------------------------------------------------------------------
# plan.json content: status excluded from the file (lives in state.json)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_json_sections_exclude_status_field(tmp_path):
    """plan.json on disk must NOT contain 'status' on sections.

    Status belongs to state.json only.  plan.json stores the raw section
    schema (id, title, hypothesis).
    """
    orch, sm, bus, client = _make_orchestrator_planning(tmp_path)
    _write_valid_plan_json(tmp_path, num_sections=3)

    await orch._handle_plan_idle()

    content = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    for section in content["sections"]:
        assert "status" not in section, (
            f"plan.json sections must NOT have 'status' field (found in {section})"
        )


# ---------------------------------------------------------------------------
# Error paths: missing / invalid plan.json → no canonical write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_ready_missing_plan_json_no_write(tmp_path):
    """Missing plan.json → turn.error; no plan.json written.

    When the input file is missing, _handle_plan_idle() must not create a
    plan.json output file (nothing valid to persist).
    """
    orch, sm, bus, client = _make_orchestrator_planning(tmp_path)
    # Do NOT write plan.json.
    plan_path = tmp_path / "plan.json"

    sub = bus.subscribe()
    await orch._handle_plan_idle()

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "turn.error"
    # plan.json must not have been written.
    assert not plan_path.exists(), "plan.json must not be written when input is missing"


@pytest.mark.asyncio
async def test_plan_ready_invalid_json_no_state_write(tmp_path):
    """Malformed plan.json → turn.error; state.json plan field unchanged.

    Invalid input must not corrupt state.json.
    """
    orch, sm, bus, client = _make_orchestrator_planning(tmp_path)
    (tmp_path / "plan.json").write_text("{not valid json", encoding="utf-8")

    # Record state before.
    state_before = sm.get_state()
    plan_before = state_before.get("plan", [])

    sub = bus.subscribe()
    await orch._handle_plan_idle()

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "turn.error"

    # State plan field must be unchanged.
    state_after = sm.get_state()
    assert state_after.get("plan") == plan_before, (
        "state.json plan must not change when input is invalid"
    )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_ready_three_sections_minimum(tmp_path):
    """plan.json with exactly 3 sections (minimum) → plan.json written, statuses set."""
    orch, sm, bus, client = _make_orchestrator_planning(tmp_path)
    _write_valid_plan_json(tmp_path, num_sections=3)

    sub = bus.subscribe()
    await orch._handle_plan_idle()

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "plan.ready"
    assert len(event["sections"]) == 3

    state = sm.get_state()
    assert len(state["plan"]) == 3
    for s in state["plan"]:
        assert s["status"] == "proposed"


@pytest.mark.asyncio
async def test_plan_ready_six_sections_maximum(tmp_path):
    """plan.json with exactly 6 sections (maximum) → plan.json written, statuses set."""
    orch, sm, bus, client = _make_orchestrator_planning(tmp_path)
    _write_valid_plan_json(tmp_path, num_sections=6)

    sub = bus.subscribe()
    await orch._handle_plan_idle()

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "plan.ready"
    assert len(event["sections"]) == 6

    state = sm.get_state()
    assert len(state["plan"]) == 6
    for s in state["plan"]:
        assert s["status"] == "proposed"


@pytest.mark.asyncio
async def test_plan_ready_preserves_section_ids_and_titles(tmp_path):
    """plan.json write preserves section id, title, hypothesis from input."""
    orch, sm, bus, client = _make_orchestrator_planning(tmp_path)
    # Write a custom plan.json with specific content.
    sections = [
        {"id": "sec_01", "title": "Churn overview", "hypothesis": "Churn is high in Q3"},
        {"id": "sec_02", "title": "Plan tier analysis", "hypothesis": "Premium churns less"},
        {"id": "sec_03", "title": "Geography breakdown", "hypothesis": "Regional variance"},
    ]
    (tmp_path / "plan.json").write_text(json.dumps({"sections": sections}), encoding="utf-8")

    await orch._handle_plan_idle()

    content = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    written_sections = content["sections"]
    assert written_sections[0]["id"] == "sec_01"
    assert written_sections[0]["title"] == "Churn overview"
    assert written_sections[0]["hypothesis"] == "Churn is high in Q3"
    assert written_sections[1]["id"] == "sec_02"
    assert written_sections[2]["id"] == "sec_03"


@pytest.mark.asyncio
async def test_plan_ready_plan_ready_event_contains_proposed_status(tmp_path):
    """plan.ready event payload sections also carry status='proposed'.

    The bus event sections should match what's persisted to state.json.
    """
    orch, sm, bus, client = _make_orchestrator_planning(tmp_path)
    _write_valid_plan_json(tmp_path, num_sections=3)

    sub = bus.subscribe()
    await orch._handle_plan_idle()

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "plan.ready"
    for section in event["sections"]:
        assert section.get("status") == "proposed", (
            f"plan.ready event sections must have status='proposed', got {section.get('status')!r}"
        )
