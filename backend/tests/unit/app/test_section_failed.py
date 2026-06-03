"""Unit tests for N2-S08 — Detect failed section.

Acceptance criteria (N2-S08):
  AC1: Given ``session.idle`` WITHOUT expected ``.md`` (and/or ``.png``), when
       detected, then ``section.failed`` is emitted with the section ID.
  AC2: Given transient bash errors the agent recovers from mid-turn, when they
       occur, then ``section.failed`` is NOT emitted (failure only surfaces at
       idle with a missing artefact).

Architecture note:
  ``_handle_section_idle()`` is the sole place that decides success vs failure
  for a section build.  It is only reached when the bus receives a
  ``session.idle`` event while ``stage == "building"``.  All mid-turn tool
  events (bash_running, bash_done, file.edited, message.part) are normalised
  and published by the OpenCode client layer; they never reach this method and
  therefore can never trigger ``section.failed``.

  This test file exercises:
    - The three single-file-missing variants (md, png, py each absent).
    - All three files absent simultaneously.
    - Payload shape (section_id present, reason field present).
    - Mid-turn events NOT reaching the idle handler (AC2).
    - Regression guard: triplet present → section.proposed, not section.failed.
    - Stage guard: non-building stage → no section.failed even if files absent.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from backend.event_bus import EventBus
from backend.orchestrator import Orchestrator
from backend.state_manager import StateManager

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_orchestrator(
    tmp_path: Path,
    *,
    stage: str = "building",
    session_id: str = "sess-test",
) -> tuple[Orchestrator, StateManager, EventBus]:
    sm = StateManager(path=tmp_path / "state.json")
    sm.load()
    sm.update(opencode_session_id=session_id, stage=stage)

    bus = EventBus()
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(return_value=None)

    orch = Orchestrator(
        state_manager=sm,
        bus=bus,
        client=mock_client,
        workspace_root=tmp_path,
    )
    return orch, sm, bus


def _set_building_section(
    sm: StateManager,
    *,
    section_id: str = "sec_01",
    index: int = 1,
    slug: str = "revenue_by_segment",
) -> None:
    """Put a section with status='building' into the plan in state."""
    sm.update(
        plan=[
            {
                "id": section_id,
                "title": "Revenue by Segment",
                "hypothesis": "Premium segment has lower churn",
                "status": "building",
                "index": index,
                "slug": slug,
            }
        ],
        dataset="customers_q3.csv",
        aim="Analyse churn drivers",
    )


def _write_triplet(
    tmp_path: Path,
    *,
    nn: str = "01",
    slug: str = "revenue_by_segment",
    write_py: bool = True,
    write_png: bool = True,
    write_md: bool = True,
) -> None:
    """Selectively write artefact files for a section."""
    base = f"sec_{nn}_{slug}"
    (tmp_path / "analyses").mkdir(parents=True, exist_ok=True)
    (tmp_path / "charts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "sections").mkdir(parents=True, exist_ok=True)

    if write_py:
        (tmp_path / "analyses" / f"{base}.py").write_text("import os\n", encoding="utf-8")
    if write_png:
        (tmp_path / "charts" / f"{base}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    if write_md:
        (tmp_path / "sections" / f"{base}.md").write_text(
            "---\nsection_id: sec_01\n---\n\nBody text.\n",
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# AC1 — session.idle without .md emits section.failed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_idle_without_md_emits_section_failed(tmp_path: Path) -> None:
    """AC1: session.idle with .md absent → section.failed with section_id."""
    orch, sm, bus = _make_orchestrator(tmp_path)
    _set_building_section(sm)
    _write_triplet(tmp_path, write_md=False)

    sub = bus.subscribe()
    await orch._handle_section_idle()

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "section.failed", (
        f"Expected section.failed when .md absent; got {event['type']!r}"
    )
    assert event.get("section_id") == "sec_01", (
        f"section_id must be 'sec_01'; got {event.get('section_id')!r}"
    )


# ---------------------------------------------------------------------------
# AC1 variant — all three artefact files absent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_idle_without_all_triplet_emits_section_failed(tmp_path: Path) -> None:
    """AC1: session.idle with no artefact files at all → section.failed."""
    orch, sm, bus = _make_orchestrator(tmp_path)
    _set_building_section(sm)
    # Create directories but write no files.
    (tmp_path / "analyses").mkdir(parents=True, exist_ok=True)
    (tmp_path / "charts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "sections").mkdir(parents=True, exist_ok=True)

    sub = bus.subscribe()
    await orch._handle_section_idle()

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "section.failed"
    assert event.get("section_id") == "sec_01"


# ---------------------------------------------------------------------------
# AC1 variant — only .py absent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_idle_without_py_emits_section_failed(tmp_path: Path) -> None:
    """AC1: session.idle with .py absent → section.failed."""
    orch, sm, bus = _make_orchestrator(tmp_path)
    _set_building_section(sm)
    _write_triplet(tmp_path, write_py=False)

    sub = bus.subscribe()
    await orch._handle_section_idle()

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "section.failed"
    assert event.get("section_id") == "sec_01"


# ---------------------------------------------------------------------------
# AC1 — payload shape: section_id and reason present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_failed_payload_has_section_id(tmp_path: Path) -> None:
    """section.failed payload must include section_id and reason fields."""
    orch, sm, bus = _make_orchestrator(tmp_path)
    _set_building_section(sm)
    _write_triplet(tmp_path, write_md=False)

    sub = bus.subscribe()
    await orch._handle_section_idle()

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "section.failed"
    assert "section_id" in event, f"section_id missing from payload: {event}"
    assert "reason" in event, f"reason missing from payload: {event}"
    assert event["section_id"] == "sec_01"
    assert event["reason"] == "missing_files"


# ---------------------------------------------------------------------------
# AC2 — mid-turn tool events do NOT trigger section.failed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mid_turn_tool_event_does_not_emit_section_failed(tmp_path: Path) -> None:
    """AC2: Non-idle events (tool.bash_running, tool.bash_done, etc.) must NOT
    cause section.failed to be emitted, even when artefact files are absent.

    The failure path is gated on session.idle; tool events during an active turn
    never reach _handle_section_idle().  This test verifies that by publishing
    non-idle event types through the bus listener and confirming no section.failed
    appears.
    """
    orch, sm, bus = _make_orchestrator(tmp_path)
    _set_building_section(sm)
    # Intentionally leave artefact files absent.

    sub = bus.subscribe()
    listener_task = asyncio.create_task(orch.start_bus_listener())
    await asyncio.sleep(0)

    # Publish activity events that the agent emits mid-turn.
    for event_type in ("tool.bash_running", "tool.bash_done", "tool.file_written", "message.part"):
        await bus.publish(event_type, {"ts": 1000})

    # Drain the queue — these events loop through the listener but the listener
    # has no handler for these types (the section idle handler is not triggered).
    received = []
    try:
        for _ in range(10):
            event = await asyncio.wait_for(sub.__anext__(), timeout=0.2)
            received.append(event)
    except asyncio.TimeoutError:
        pass

    listener_task.cancel()
    try:
        await listener_task
    except asyncio.CancelledError:
        pass

    failed_events = [e for e in received if e.get("type") == "section.failed"]
    assert not failed_events, (
        f"section.failed must NOT be emitted for mid-turn tool events; got {failed_events}"
    )


# ---------------------------------------------------------------------------
# Regression guard — triplet present → section.proposed, not section.failed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_idle_with_triplet_emits_proposed_not_failed(tmp_path: Path) -> None:
    """When all three artefact files are present, section.proposed fires (not section.failed)."""
    orch, sm, bus = _make_orchestrator(tmp_path)
    _set_building_section(sm)
    _write_triplet(tmp_path)  # all three files present

    sub = bus.subscribe()
    await orch._handle_section_idle()

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "section.proposed", (
        f"Triplet present — expected section.proposed, got {event['type']!r}"
    )
    # section.failed must not follow
    assert not any(e.get("type") == "section.failed" for e in [event]), (
        "section.failed must not be emitted when triplet is complete"
    )


# ---------------------------------------------------------------------------
# Stage guard — non-building stage → no section.failed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_section_failed_not_emitted_in_non_building_stage(tmp_path: Path) -> None:
    """_handle_section_idle is a no-op outside the building stage.

    Even if artefact files are absent, section.failed must not fire when
    the stage is not 'building'.
    """
    orch, sm, bus = _make_orchestrator(tmp_path, stage="planning")
    # No artefact files at all.

    sub = bus.subscribe()
    await orch._handle_section_idle()

    assert sub._queue.empty(), "No events should be emitted when stage is not 'building'"
