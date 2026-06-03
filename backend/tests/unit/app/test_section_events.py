"""Unit tests for N2-S07 — Section build events.

TDD: tests written before implementation.

Acceptance criteria covered (N2-S07):
- Tool/file/message events during the turn surface as section.building activity:
  already handled by _normalise_and_publish (existing path); confirmed by
  test_section_building_activity_flows_via_normalise_and_publish.
- session.idle with expected triplet present → section.proposed emitted with
  section_id, md_path, py_path, png_path.
- file.ready emitted for chart via existing file.edited → file.ready path
  (already tested in test_event_subscription.py).
- Wrong stage at session.idle → no section dispatch.

Architecture constraints verified:
- orchestrator.py does not import httpx (inherited from existing AST check).
- section.building domain event emitted before OpenCode round-trip completes.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.event_bus import EventBus
from backend.orchestrator import Orchestrator
from backend.state_manager import StateManager

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_state_manager(
    tmp_path: Path,
    *,
    session_id: str | None = "sess-abc",
    stage: str = "building",
) -> StateManager:
    sm = StateManager(path=tmp_path / "state.json")
    sm.load()
    if session_id is not None:
        sm.update(opencode_session_id=session_id)
    sm.update(stage=stage)
    return sm


def _make_orchestrator(
    tmp_path: Path,
    *,
    session_id: str | None = "sess-abc",
    stage: str = "building",
) -> tuple[Orchestrator, StateManager, EventBus, AsyncMock]:
    sm = _make_state_manager(tmp_path, session_id=session_id, stage=stage)
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


def _write_section_triplet(
    tmp_path: Path,
    *,
    section_id: str = "sec_01",
    nn: str = "01",
    slug: str = "churn_by_tier",
    write_md: bool = True,
    write_png: bool = True,
    write_py: bool = True,
) -> dict[str, Path]:
    """Write the three section artefact files to the workspace.

    Returns paths dict with keys 'py', 'png', 'md'.
    """
    base = f"sec_{nn}_{slug}"
    analyses_dir = tmp_path / "analyses"
    charts_dir = tmp_path / "charts"
    sections_dir = tmp_path / "sections"
    analyses_dir.mkdir(parents=True, exist_ok=True)
    charts_dir.mkdir(parents=True, exist_ok=True)
    sections_dir.mkdir(parents=True, exist_ok=True)

    py_path = analyses_dir / f"{base}.py"
    png_path = charts_dir / f"{base}.png"
    md_path = sections_dir / f"{base}.md"

    if write_py:
        py_path.write_text("import matplotlib\n", encoding="utf-8")
    if write_png:
        png_path.write_bytes(b"\x89PNG\r\n\x1a\n")  # minimal PNG header
    if write_md:
        md_content = (
            "---\n"
            f"section_id: {section_id}\n"
            f'title: "Churn by Tier"\n'
            f'hypothesis: "Higher tiers churn less"\n'
            f"chart: charts/{base}.png\n"
            "---\n\n"
            "Churn rates decrease with higher service tier.\n"
        )
        md_path.write_text(md_content, encoding="utf-8")

    return {"py": py_path, "png": png_path, "md": md_path}


def _set_building_section(sm: StateManager, section_id: str, nn: str, slug: str) -> None:
    """Add a section with status 'building' to state.json plan."""
    plan = [
        {
            "id": section_id,
            "title": "Churn by Tier",
            "hypothesis": "Higher tiers churn less",
            "status": "building",
            "index": int(nn),
            "slug": slug,
        }
    ]
    sm.update(plan=plan, dataset="customers_q3.csv", aim="Analyse churn")


# ---------------------------------------------------------------------------
# 1. section.proposed emitted when triplet present at session.idle (building)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_section_idle_emits_section_proposed(tmp_path: Path) -> None:
    """All three triplet files present + building stage → section.proposed emitted."""
    orch, sm, bus, client = _make_orchestrator(tmp_path)
    _set_building_section(sm, "sec_01", "01", "churn_by_tier")
    _write_section_triplet(tmp_path)

    sub = bus.subscribe()
    await orch._handle_section_idle()

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "section.proposed", f"Expected section.proposed; got {event['type']!r}"


# ---------------------------------------------------------------------------
# 2. section.proposed payload has required fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_section_idle_proposed_payload(tmp_path: Path) -> None:
    """section.proposed must include section_id, md_path, py_path, png_path."""
    orch, sm, bus, client = _make_orchestrator(tmp_path)
    _set_building_section(sm, "sec_01", "01", "churn_by_tier")
    _write_section_triplet(tmp_path)

    sub = bus.subscribe()
    await orch._handle_section_idle()

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "section.proposed"
    assert event.get("section_id") == "sec_01", f"Missing or wrong section_id: {event}"
    assert "md_path" in event, f"md_path missing from payload: {event}"
    assert "py_path" in event, f"py_path missing from payload: {event}"
    assert "png_path" in event, f"png_path missing from payload: {event}"
    assert "ts" in event, f"ts missing from payload: {event}"

    # Paths should be relative workspace paths (not absolute)
    assert not event["md_path"].startswith("/"), f"md_path should be relative: {event['md_path']}"
    assert not event["png_path"].startswith("/"), (
        f"png_path should be relative: {event['png_path']}"
    )
    assert not event["py_path"].startswith("/"), f"py_path should be relative: {event['py_path']}"


# ---------------------------------------------------------------------------
# 3. section.failed when .md absent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_section_idle_missing_md_emits_section_failed(tmp_path: Path) -> None:
    """Missing .md file at session.idle → section.failed emitted."""
    orch, sm, bus, client = _make_orchestrator(tmp_path)
    _set_building_section(sm, "sec_01", "01", "churn_by_tier")
    _write_section_triplet(tmp_path, write_md=False)  # .md absent

    sub = bus.subscribe()
    await orch._handle_section_idle()

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "section.failed", f"Expected section.failed; got {event['type']!r}"
    assert event.get("section_id") == "sec_01"
    assert event.get("reason") == "missing_files"


# ---------------------------------------------------------------------------
# 4. section.failed when .png absent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_section_idle_missing_png_emits_section_failed(tmp_path: Path) -> None:
    """Missing .png file at session.idle → section.failed emitted."""
    orch, sm, bus, client = _make_orchestrator(tmp_path)
    _set_building_section(sm, "sec_01", "01", "churn_by_tier")
    _write_section_triplet(tmp_path, write_png=False)  # .png absent

    sub = bus.subscribe()
    await orch._handle_section_idle()

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "section.failed"
    assert event.get("reason") == "missing_files"


# ---------------------------------------------------------------------------
# 5. section.building domain event emitted by start_build_section
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_build_section_emits_section_building(tmp_path: Path) -> None:
    """start_build_section() emits section.building domain event."""
    orch, sm, bus, client = _make_orchestrator(tmp_path)

    # Set up state with a plan section
    sm.update(
        stage="building",
        dataset="customers_q3.csv",
        aim="Analyse churn",
        plan=[
            {
                "id": "sec_01",
                "title": "Churn by Tier",
                "hypothesis": "Higher tiers churn less",
                "status": "queued",
            }
        ],
    )

    profile = {"shape": {"rows": 100, "columns": 5}, "columns": [], "flags": []}
    sub = bus.subscribe()

    await orch.start_build_section(
        section_id="sec_01",
        section_index=1,
        title="Churn by Tier",
        hypothesis="Higher tiers churn less",
        profile=profile,
    )
    # Allow fire-and-forget prompt task to run.
    await asyncio.sleep(0)

    # Collect events — we expect section.building to be first (before OpenCode response)
    received = []
    try:
        for _ in range(3):
            event = await asyncio.wait_for(sub.__anext__(), timeout=0.5)
            received.append(event)
    except asyncio.TimeoutError:
        pass

    types = [e["type"] for e in received]
    assert "section.building" in types, f"Expected section.building in {types}"
    building_event = next(e for e in received if e["type"] == "section.building")
    assert building_event.get("section_id") == "sec_01"
    assert building_event.get("title") == "Churn by Tier"


# ---------------------------------------------------------------------------
# 6. start_build_section calls client.prompt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_build_section_calls_prompt(tmp_path: Path) -> None:
    """start_build_section() dispatches client.prompt with session_id and non-empty text."""
    orch, sm, bus, client = _make_orchestrator(tmp_path)
    sm.update(
        stage="building",
        dataset="customers_q3.csv",
        aim="Analyse churn",
        plan=[
            {
                "id": "sec_01",
                "title": "Churn by Tier",
                "hypothesis": "Higher tiers churn less",
                "status": "queued",
            }
        ],
    )

    profile = {"shape": {"rows": 100, "columns": 5}, "columns": [], "flags": []}

    await orch.start_build_section(
        section_id="sec_01",
        section_index=1,
        title="Churn by Tier",
        hypothesis="Higher tiers churn less",
        profile=profile,
    )
    await asyncio.sleep(0)

    client.prompt.assert_awaited_once()
    args, kwargs = client.prompt.call_args
    assert args[0] == "sess-abc", f"Expected session_id 'sess-abc'; got {args[0]!r}"
    assert isinstance(args[1], str) and len(args[1]) > 0, "Prompt text must be non-empty"
    # schema must NOT be passed for section build (ADR-005: no structured output)
    schema_arg = kwargs.get("schema", args[2] if len(args) > 2 else None)
    assert schema_arg is None, (
        f"schema must be None for section build (ADR-005); got {schema_arg!r}"
    )


# ---------------------------------------------------------------------------
# 7. start_build_section arms watchdog
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_build_section_arms_watchdog(tmp_path: Path) -> None:
    """start_build_section() calls watchdog.start_turn() when watchdog is wired."""
    sm = _make_state_manager(tmp_path, session_id="sess-abc", stage="building")
    sm.update(
        dataset="customers_q3.csv",
        aim="Analyse churn",
        plan=[
            {
                "id": "sec_01",
                "title": "Churn by Tier",
                "hypothesis": "Higher tiers churn less",
                "status": "queued",
            }
        ],
    )
    bus = EventBus()
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(return_value=None)
    watchdog = MagicMock()
    watchdog.start_turn = MagicMock()

    orch = Orchestrator(
        state_manager=sm,
        bus=bus,
        client=mock_client,
        workspace_root=tmp_path,
        watchdog=watchdog,
    )

    profile = {"shape": {"rows": 100, "columns": 5}, "columns": [], "flags": []}
    await orch.start_build_section(
        section_id="sec_01",
        section_index=1,
        title="Churn by Tier",
        hypothesis="Higher tiers churn less",
        profile=profile,
    )
    await asyncio.sleep(0)

    watchdog.start_turn.assert_called_once()


# ---------------------------------------------------------------------------
# 8. Wrong stage at session.idle → no section dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_idle_wrong_stage_no_section_dispatch(tmp_path: Path) -> None:
    """session.idle in non-building stage does not trigger section.proposed."""
    # Use planning stage — should dispatch to plan handler, not section handler
    orch, sm, bus, client = _make_orchestrator(tmp_path, stage="planning")

    # Write a valid plan.json so plan idle handler can succeed
    sections = [
        {"id": f"sec_{i:02d}", "title": f"Section {i}", "hypothesis": f"H{i}"} for i in range(1, 4)
    ]
    (tmp_path / "plan.json").write_text(json.dumps({"sections": sections}), encoding="utf-8")

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
    assert "section.proposed" not in types, (
        f"section.proposed must not fire in planning stage; got {types}"
    )
    assert "section.failed" not in types, (
        f"section.failed must not fire in planning stage; got {types}"
    )


# ---------------------------------------------------------------------------
# 9. start_build_section raises ValueError when no session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_build_section_raises_without_session(tmp_path: Path) -> None:
    """start_build_section() raises ValueError when no session_id is stored."""
    sm = _make_state_manager(tmp_path, session_id=None, stage="building")
    sm.update(dataset="customers_q3.csv", aim="Analyse churn")
    bus = EventBus()
    mock_client = AsyncMock()
    orch = Orchestrator(state_manager=sm, bus=bus, client=mock_client, workspace_root=tmp_path)

    profile = {"shape": {"rows": 100, "columns": 5}, "columns": [], "flags": []}
    with pytest.raises(ValueError, match="No active session"):
        await orch.start_build_section(
            section_id="sec_01",
            section_index=1,
            title="Churn by Tier",
            hypothesis="Higher tiers churn less",
            profile=profile,
        )


# ---------------------------------------------------------------------------
# 10. Handle session.idle in building stage via bus listener
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bus_listener_session_idle_building_stage(tmp_path: Path) -> None:
    """start_bus_listener dispatches to _handle_section_idle when stage=building."""
    orch, sm, bus, client = _make_orchestrator(tmp_path)
    _set_building_section(sm, "sec_01", "01", "churn_by_tier")
    _write_section_triplet(tmp_path)

    sub = bus.subscribe()
    listener_task = asyncio.create_task(orch.start_bus_listener())
    await asyncio.sleep(0)

    # Fire session.idle
    await bus.publish("session.idle", {"ts": 123})

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
    assert "section.proposed" in types, f"Expected section.proposed from bus listener; got {types}"


# ---------------------------------------------------------------------------
# 11. _handle_section_idle no-op when stage is not building
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_section_idle_wrong_stage_returns_early(tmp_path: Path) -> None:
    """_handle_section_idle is a no-op when stage != building."""
    orch, sm, bus, client = _make_orchestrator(tmp_path, stage="planning")
    _write_section_triplet(tmp_path)

    sub = bus.subscribe()
    await orch._handle_section_idle()

    assert sub._queue.empty(), "No events should be emitted when stage != building"


# ---------------------------------------------------------------------------
# 12. _handle_section_idle no-op when no building section in plan
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_section_idle_no_building_section_returns_early(tmp_path: Path) -> None:
    """_handle_section_idle is a no-op when no section has status building in plan."""
    orch, sm, bus, client = _make_orchestrator(tmp_path)
    # Plan exists but no section is 'building'
    sm.update(
        plan=[
            {
                "id": "sec_01",
                "title": "Churn by Tier",
                "hypothesis": "Higher tiers churn less",
                "status": "queued",  # not building
            }
        ]
    )

    sub = bus.subscribe()
    await orch._handle_section_idle()

    assert sub._queue.empty(), "No events should be emitted when no section has status=building"
