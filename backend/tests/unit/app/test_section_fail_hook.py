"""Unit tests for N2-S20 -- Forced section-failure test hook.

Acceptance criteria (N2-S20):
  AC1: Given ``QA_FORCE_SECTION_FAIL=1`` is set, when a section build turn
       idles, then no ``sections/<id>.md`` is present (or it is removed) and
       ``section.failed`` is emitted with the section ID.
  AC2: Given ``QA_FORCE_SECTION_FAIL`` is unset (or ``0``), when a build runs,
       then behaviour is unchanged (triplet present -> ``section.proposed``).

Architecture:
  The seam sits at the top of ``_handle_section_idle()`` in ``orchestrator.py``
  — the same method that N2-S08 tests exercise.  When ``QA_FORCE_SECTION_FAIL=1``
  is set, the method deletes the ``.md`` file (if present) before the existing
  triplet check runs, causing the normal ``section.failed`` path to fire.

  This is consistent with the ``QA_FORCE_STALL`` seam in ``opencode_client.py``
  (N1-S20): an env-var that is off by default and has zero impact on any
  production code path.

Test coverage:
  - AC1: hook set, full triplet present -> section.failed emitted.
  - AC1: hook set, .md removed from disk after the call (side-effect check).
  - AC1: hook set, .md already absent -> section.failed still emitted (no crash).
  - AC1: section_id present in section.failed payload.
  - AC2: hook unset, full triplet present -> section.proposed (no regression).
  - AC2: hook explicitly ``0``, full triplet present -> section.proposed.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from backend.event_bus import EventBus
from backend.orchestrator import Orchestrator
from backend.state_manager import StateManager

# ---------------------------------------------------------------------------
# Shared helpers (mirror test_section_failed.py conventions)
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
# AC1 — hook set, full triplet present -> section.failed emitted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_force_fail_env_set_emits_section_failed(tmp_path: Path) -> None:
    """AC1: QA_FORCE_SECTION_FAIL=1 + full triplet on disk -> section.failed."""
    orch, sm, bus = _make_orchestrator(tmp_path)
    _set_building_section(sm)
    _write_triplet(tmp_path)  # All three files present

    sub = bus.subscribe()
    with patch.dict("os.environ", {"QA_FORCE_SECTION_FAIL": "1"}):
        await orch._handle_section_idle()

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "section.failed", (
        f"Expected section.failed with QA_FORCE_SECTION_FAIL=1; got {event['type']!r}"
    )


# ---------------------------------------------------------------------------
# AC1 — hook set, .md removed from disk after the call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_force_fail_env_set_removes_md_file(tmp_path: Path) -> None:
    """AC1: QA_FORCE_SECTION_FAIL=1 removes the .md file from disk."""
    orch, sm, bus = _make_orchestrator(tmp_path)
    _set_building_section(sm)
    _write_triplet(tmp_path)  # All three files present

    md_path = tmp_path / "sections" / "sec_01_revenue_by_segment.md"
    assert md_path.exists(), "Pre-condition: .md must exist before the call"

    sub = bus.subscribe()  # drain the bus so publish doesn't block
    with patch.dict("os.environ", {"QA_FORCE_SECTION_FAIL": "1"}):
        await orch._handle_section_idle()

    # Drain the event
    await asyncio.wait_for(sub.__anext__(), timeout=1.0)

    assert not md_path.exists(), (
        "QA_FORCE_SECTION_FAIL=1 must delete the .md file before the triplet check"
    )


# ---------------------------------------------------------------------------
# AC1 — hook set, .md already absent -> section.failed (no crash)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_force_fail_with_no_md_present_still_emits_failed(tmp_path: Path) -> None:
    """AC1: QA_FORCE_SECTION_FAIL=1, .md absent -> section.failed without error."""
    orch, sm, bus = _make_orchestrator(tmp_path)
    _set_building_section(sm)
    # Write py + png but NOT md (simulates OpenCode never writing it).
    _write_triplet(tmp_path, write_md=False)

    sub = bus.subscribe()
    with patch.dict("os.environ", {"QA_FORCE_SECTION_FAIL": "1"}):
        await orch._handle_section_idle()

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "section.failed", (
        f"Expected section.failed even when .md was already absent; got {event['type']!r}"
    )


# ---------------------------------------------------------------------------
# AC1 — section_id present in section.failed payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_force_fail_section_id_in_payload(tmp_path: Path) -> None:
    """AC1: section.failed payload includes the correct section_id."""
    orch, sm, bus = _make_orchestrator(tmp_path)
    _set_building_section(sm, section_id="sec_02", index=2, slug="churn_rate_trend")
    _write_triplet(tmp_path, nn="02", slug="churn_rate_trend")

    sub = bus.subscribe()
    with patch.dict("os.environ", {"QA_FORCE_SECTION_FAIL": "1"}):
        await orch._handle_section_idle()

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "section.failed"
    assert event.get("section_id") == "sec_02", (
        f"section_id must be 'sec_02'; got {event.get('section_id')!r}"
    )
    assert "reason" in event, f"reason field missing from payload: {event}"


# ---------------------------------------------------------------------------
# AC2 — hook unset: behaviour unchanged, section.proposed emitted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_force_fail_env_unset_behaviour_unchanged_proposed(tmp_path: Path) -> None:
    """AC2: QA_FORCE_SECTION_FAIL not set + full triplet -> section.proposed."""
    orch, sm, bus = _make_orchestrator(tmp_path)
    _set_building_section(sm)
    _write_triplet(tmp_path)

    sub = bus.subscribe()
    # Explicitly ensure the env var is not set.
    with patch.dict("os.environ", {}, clear=False):
        import os

        os.environ.pop("QA_FORCE_SECTION_FAIL", None)
        await orch._handle_section_idle()

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "section.proposed", (
        f"Without QA_FORCE_SECTION_FAIL, full triplet must yield section.proposed; "
        f"got {event['type']!r}"
    )


# ---------------------------------------------------------------------------
# AC2 — hook explicitly "0": behaviour unchanged, section.proposed emitted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_force_fail_env_zero_behaviour_unchanged_proposed(tmp_path: Path) -> None:
    """AC2: QA_FORCE_SECTION_FAIL=0 + full triplet -> section.proposed (hook is off)."""
    orch, sm, bus = _make_orchestrator(tmp_path)
    _set_building_section(sm)
    _write_triplet(tmp_path)

    sub = bus.subscribe()
    with patch.dict("os.environ", {"QA_FORCE_SECTION_FAIL": "0"}):
        await orch._handle_section_idle()

    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert event["type"] == "section.proposed", (
        f"QA_FORCE_SECTION_FAIL=0 must be treated as hook-off; "
        f"full triplet must yield section.proposed; got {event['type']!r}"
    )
