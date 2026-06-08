"""Unit tests for POST /section/:id/drop.

TDD: tests written before the implementation.

Acceptance criteria covered:
- POST /section/:id/drop → section marked dropped, returns 204.
- No OpenCode call made.
- Unknown ID → 400 section_not_found error envelope.
- Section not in proposed status → 400 section_not_proposed error envelope.
- Dropped sections excluded from export (GET /export only includes accepted; verified
  separately, but drop status is correct precondition).

Architecture constraint:
- Zero OpenCode calls (verified via mock).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.core.state_manager import StateManager
from backend.main import app

# ---------------------------------------------------------------------------
# Shared fixture helpers
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


# ---------------------------------------------------------------------------
# Happy path — 204 + status updated to dropped
# ---------------------------------------------------------------------------


def test_section_drop_returns_204(tmp_path: Path):
    """POST /section/sec_01/drop returns 204 No Content."""
    state_path = tmp_path / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(stage="building", plan=list(_PLAN_WITH_PROPOSED))

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            r = c.post("/api/section/sec_01/drop")

    assert r.status_code == 204


def test_section_drop_updates_status_to_dropped(tmp_path: Path):
    """POST /section/sec_01/drop sets the section status to 'dropped'."""
    state_path = tmp_path / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(stage="building", plan=list(_PLAN_WITH_PROPOSED))

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            c.post("/api/section/sec_01/drop")

    plan = sm.get_state()["plan"]
    sec_01 = next(s for s in plan if s["id"] == "sec_01")
    assert sec_01["status"] == "dropped", f"Expected 'dropped', got {sec_01['status']!r}"


def test_section_drop_only_mutates_target_section(tmp_path: Path):
    """POST /section/sec_01/drop leaves other sections unchanged."""
    state_path = tmp_path / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(stage="building", plan=list(_PLAN_WITH_PROPOSED))

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            c.post("/api/section/sec_01/drop")

    plan = sm.get_state()["plan"]
    sec_02 = next(s for s in plan if s["id"] == "sec_02")
    assert sec_02["status"] == "proposed", (
        f"sec_02 should remain 'proposed', got {sec_02['status']!r}"
    )


def test_section_drop_second_section(tmp_path: Path):
    """POST /section/sec_02/drop marks the second section dropped."""
    state_path = tmp_path / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(stage="building", plan=list(_PLAN_WITH_PROPOSED))

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            r = c.post("/api/section/sec_02/drop")

    assert r.status_code == 204
    plan = sm.get_state()["plan"]
    sec_02 = next(s for s in plan if s["id"] == "sec_02")
    assert sec_02["status"] == "dropped"


def test_section_drop_failed_section(tmp_path: Path):
    """POST /section/sec_01/drop permits the user to skip a failed section."""
    plan = [
        {
            "id": "sec_01",
            "title": "Cohort overview",
            "hypothesis": "Baseline",
            "status": "failed",
        },
    ]
    state_path = tmp_path / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(stage="building", plan=plan)

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            r = c.post("/api/section/sec_01/drop")

    assert r.status_code == 204
    assert sm.get_state()["plan"][0]["status"] == "dropped"


def test_section_drop_clears_failure_reason(tmp_path: Path):
    """Dropping a failed section clears its persisted failure_reason."""
    plan = [
        {
            "id": "sec_01",
            "title": "Cohort overview",
            "hypothesis": "Baseline",
            "status": "failed",
            "failure_reason": "missing_files",
        },
    ]
    state_path = tmp_path / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(stage="building", plan=plan)

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            r = c.post("/api/section/sec_01/drop")

    assert r.status_code == 204
    section = sm.get_state()["plan"][0]
    assert section["status"] == "dropped"
    assert section["failure_reason"] is None


def test_section_drop_advances_build_queue(tmp_path: Path):
    """Dropping a proposed section releases the next queued section."""
    state_path = tmp_path / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(stage="building", plan=list(_PLAN_WITH_PROPOSED))

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            c.app.state.orchestrator._start_next_queued_section = AsyncMock(return_value=None)
            c.post("/api/section/sec_01/drop")

    c.app.state.orchestrator._start_next_queued_section.assert_awaited_once()


# ---------------------------------------------------------------------------
# Error path — unknown section ID
# ---------------------------------------------------------------------------


def test_section_drop_unknown_id_returns_400(tmp_path: Path):
    """POST /section/sec_99/drop returns 400 with section_not_found."""
    state_path = tmp_path / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(stage="building", plan=list(_PLAN_WITH_PROPOSED))

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            r = c.post("/api/section/sec_99/drop")

    assert r.status_code == 400
    body = r.json()
    assert body.get("error") == "section_not_found"
    assert "sec_99" in body.get("message", "")


def test_section_drop_unknown_id_error_envelope_shape(tmp_path: Path):
    """Error envelope must have 'error' and 'message' keys (contract §4)."""
    state_path = tmp_path / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(stage="building", plan=list(_PLAN_WITH_PROPOSED))

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            r = c.post("/api/section/sec_99/drop")

    body = r.json()
    assert "error" in body
    assert "message" in body


# ---------------------------------------------------------------------------
# Error path — section not in proposed status
# ---------------------------------------------------------------------------


def test_section_drop_already_accepted_returns_400(tmp_path: Path):
    """POST /section/sec_01/drop on an already-accepted section returns 400."""
    plan = [
        {
            "id": "sec_01",
            "title": "Cohort overview",
            "hypothesis": "Baseline",
            "status": "accepted",
        },
    ]
    state_path = tmp_path / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(stage="building", plan=plan)

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            r = c.post("/api/section/sec_01/drop")

    assert r.status_code == 400
    body = r.json()
    assert body.get("error") == "section_not_proposed"


def test_section_drop_already_dropped_returns_400(tmp_path: Path):
    """POST /section/sec_01/drop on an already-dropped section returns 400."""
    plan = [
        {
            "id": "sec_01",
            "title": "Cohort overview",
            "hypothesis": "Baseline",
            "status": "dropped",
        },
    ]
    state_path = tmp_path / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(stage="building", plan=plan)

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            r = c.post("/api/section/sec_01/drop")

    assert r.status_code == 400
    body = r.json()
    assert body.get("error") == "section_not_proposed"


# ---------------------------------------------------------------------------
# Edge case — empty plan
# ---------------------------------------------------------------------------


def test_section_drop_empty_plan_returns_400(tmp_path: Path):
    """POST /section/sec_01/drop with an empty plan returns 400 section_not_found."""
    state_path = tmp_path / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(stage="building", plan=[])

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            r = c.post("/api/section/sec_01/drop")

    assert r.status_code == 400
    body = r.json()
    assert body.get("error") == "section_not_found"


# ---------------------------------------------------------------------------
# Export exclusion — dropped section not included in GET /export
# ---------------------------------------------------------------------------


def test_section_drop_excluded_from_export(tmp_path: Path):
    """After dropping a section, GET /export must not include its content.

    Creates a sections/ .md file for sec_01 then drops sec_01; the export
    body must not contain the section content.
    """
    state_path = tmp_path / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(stage="building", plan=list(_PLAN_WITH_PROPOSED))

    # Write a fake section file for sec_01.
    sections_dir = tmp_path / "sections"
    sections_dir.mkdir(parents=True, exist_ok=True)
    sec_file = sections_dir / "sec_01_cohort_overview.md"
    sec_file.write_text(
        "---\nsection_id: sec_01\ntitle: Cohort overview\n---\n\nSecret content here.\n",
        encoding="utf-8",
    )

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            # Drop sec_01.
            c.post("/api/section/sec_01/drop")
            # Export must not include sec_01 content.
            r = c.get("/api/export")

    assert r.status_code == 200
    assert "Secret content here" not in r.text


# ---------------------------------------------------------------------------
# Zero OpenCode calls
# ---------------------------------------------------------------------------


def test_section_drop_makes_zero_opencode_calls(tmp_path: Path):
    """POST /section/sec_01/drop must make zero calls to the OpenCode client."""
    state_path = tmp_path / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(stage="building", plan=list(_PLAN_WITH_PROPOSED))

    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(return_value=None)

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            c.app.state.orchestrator._client = mock_client
            c.post("/api/section/sec_01/drop")

    mock_client.prompt.assert_not_awaited()
