"""Unit tests for POST /plan/update.

TDD: tests written before the implementation.

Acceptance criteria covered:
- POST /plan/update with valid sections → state.json mutates, returns {"ok": true}.
- plan.json written to workspace.
- Existing section statuses preserved where IDs match.
- New sections get status="proposed".
- Invalid request (missing/empty sections) → 422 error envelope.
- Zero OpenCode calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.core.state_manager import StateManager
from backend.main import app

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_EXISTING_PLAN = [
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
        "status": "accepted",
    },
]

_REPLACEMENT_SECTIONS = [
    {
        "id": "sec_01",
        "title": "Updated cohort overview",
        "hypothesis": "Revised hypothesis",
    },
    {
        "id": "sec_02",
        "title": "Churn by tier",
        "hypothesis": "Tier drives churn",
    },
    {
        "id": "sec_03",
        "title": "New section",
        "hypothesis": "Brand new",
    },
]


def _make_sm(tmp_path: Path, plan: list | None = None) -> StateManager:
    sm = StateManager(path=tmp_path / "state.json")
    sm.load()
    sm.update(stage="planning", plan=plan if plan is not None else list(_EXISTING_PLAN))
    return sm


# ---------------------------------------------------------------------------
# Happy path — 200 {"ok": true} + state.json updated
# ---------------------------------------------------------------------------


def test_plan_update_returns_ok(tmp_path: Path):
    """POST /plan/update with valid sections returns {"ok": true}."""
    sm = _make_sm(tmp_path)

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            r = c.post("/api/plan/update", json={"sections": _REPLACEMENT_SECTIONS})

    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_plan_update_persists_sections_to_state(tmp_path: Path):
    """POST /plan/update persists the new plan array to state.json."""
    sm = _make_sm(tmp_path)

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            c.post("/api/plan/update", json={"sections": _REPLACEMENT_SECTIONS})

    plan = sm.get_state()["plan"]
    assert len(plan) == 3
    titles = [s["title"] for s in plan]
    assert "Updated cohort overview" in titles
    assert "New section" in titles


def test_plan_update_preserves_existing_status(tmp_path: Path):
    """POST /plan/update preserves the status of existing sections."""
    sm = _make_sm(tmp_path)

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            c.post("/api/plan/update", json={"sections": _REPLACEMENT_SECTIONS})

    plan = sm.get_state()["plan"]
    sec_01 = next(s for s in plan if s["id"] == "sec_01")
    sec_02 = next(s for s in plan if s["id"] == "sec_02")

    # sec_01 was "proposed" → stays "proposed"
    assert sec_01["status"] == "proposed", f"sec_01 should be 'proposed', got {sec_01['status']!r}"
    # sec_02 was "accepted" → stays "accepted"
    assert sec_02["status"] == "accepted", f"sec_02 should be 'accepted', got {sec_02['status']!r}"


def test_plan_update_new_sections_get_proposed_status(tmp_path: Path):
    """POST /plan/update gives new sections (new IDs) status='proposed'."""
    sm = _make_sm(tmp_path)

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            c.post("/api/plan/update", json={"sections": _REPLACEMENT_SECTIONS})

    plan = sm.get_state()["plan"]
    sec_03 = next(s for s in plan if s["id"] == "sec_03")
    assert sec_03["status"] == "proposed", (
        f"New section should be 'proposed', got {sec_03['status']!r}"
    )


def test_plan_update_writes_plan_json(tmp_path: Path):
    """POST /plan/update writes plan.json to the workspace directory."""
    sm = _make_sm(tmp_path)

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            c.post("/api/plan/update", json={"sections": _REPLACEMENT_SECTIONS})

    plan_file = tmp_path / "plan.json"
    assert plan_file.exists(), "plan.json should be written to workspace"
    content = json.loads(plan_file.read_text())
    assert "sections" in content
    assert len(content["sections"]) == 3


def test_plan_update_plan_json_has_no_status_field(tmp_path: Path):
    """plan.json written by POST /plan/update must NOT contain status fields."""
    sm = _make_sm(tmp_path)

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            c.post("/api/plan/update", json={"sections": _REPLACEMENT_SECTIONS})

    plan_file = tmp_path / "plan.json"
    content = json.loads(plan_file.read_text())
    for section in content["sections"]:
        assert "status" not in section, f"plan.json section should not have status field: {section}"


def test_plan_update_reorder_sections(tmp_path: Path):
    """POST /plan/update with reordered sections persists in the new order."""
    sm = _make_sm(tmp_path)
    # Send sec_02 first, then sec_01
    reordered = [
        {"id": "sec_02", "title": "Churn by tier", "hypothesis": "Tier drives churn"},
        {"id": "sec_01", "title": "Cohort overview", "hypothesis": "Establish churn rate"},
    ]

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            r = c.post("/api/plan/update", json={"sections": reordered})

    assert r.status_code == 200
    plan = sm.get_state()["plan"]
    assert plan[0]["id"] == "sec_02"
    assert plan[1]["id"] == "sec_01"


def test_plan_update_single_section(tmp_path: Path):
    """POST /plan/update with a single section succeeds (boundary: min 1)."""
    sm = _make_sm(tmp_path)
    single = [{"id": "sec_01", "title": "Only section", "hypothesis": "Single hyp"}]

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            r = c.post("/api/plan/update", json={"sections": single})

    assert r.status_code == 200
    plan = sm.get_state()["plan"]
    assert len(plan) == 1
    assert plan[0]["title"] == "Only section"


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_plan_update_missing_sections_key_returns_422(tmp_path: Path):
    """POST /plan/update with missing 'sections' key returns 422."""
    sm = _make_sm(tmp_path)

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            r = c.post("/api/plan/update", json={"other": "field"})

    assert r.status_code == 422
    body = r.json()
    assert "error" in body


def test_plan_update_empty_sections_returns_422(tmp_path: Path):
    """POST /plan/update with empty sections array returns 422."""
    sm = _make_sm(tmp_path)

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            r = c.post("/api/plan/update", json={"sections": []})

    assert r.status_code == 422
    body = r.json()
    assert "error" in body


def test_plan_update_sections_not_list_returns_422(tmp_path: Path):
    """POST /plan/update with non-list sections returns 422."""
    sm = _make_sm(tmp_path)

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            r = c.post("/api/plan/update", json={"sections": "not a list"})

    assert r.status_code == 422
    body = r.json()
    assert "error" in body


def test_plan_update_section_missing_id_returns_422(tmp_path: Path):
    """POST /plan/update with a section missing 'id' returns 422."""
    sm = _make_sm(tmp_path)
    bad_sections = [{"title": "No id", "hypothesis": "Missing id field"}]

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            r = c.post("/api/plan/update", json={"sections": bad_sections})

    assert r.status_code == 422
    body = r.json()
    assert "error" in body


def test_plan_update_section_missing_title_returns_422(tmp_path: Path):
    """POST /plan/update with a section missing 'title' returns 422."""
    sm = _make_sm(tmp_path)
    bad_sections = [{"id": "sec_01", "hypothesis": "No title"}]

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            r = c.post("/api/plan/update", json={"sections": bad_sections})

    assert r.status_code == 422
    body = r.json()
    assert "error" in body


def test_plan_update_section_missing_hypothesis_returns_422(tmp_path: Path):
    """POST /plan/update with a section missing 'hypothesis' returns 422."""
    sm = _make_sm(tmp_path)
    bad_sections = [{"id": "sec_01", "title": "No hypothesis"}]

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            r = c.post("/api/plan/update", json={"sections": bad_sections})

    assert r.status_code == 422
    body = r.json()
    assert "error" in body


# ---------------------------------------------------------------------------
# Zero OpenCode calls
# ---------------------------------------------------------------------------


def test_plan_update_makes_zero_opencode_calls(tmp_path: Path):
    """POST /plan/update must make zero calls to the OpenCode client."""
    sm = _make_sm(tmp_path)
    mock_client = AsyncMock()
    mock_client.prompt = AsyncMock(return_value=None)

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            c.app.state.orchestrator._client = mock_client
            c.post("/api/plan/update", json={"sections": _REPLACEMENT_SECTIONS})

    mock_client.prompt.assert_not_awaited()


# ---------------------------------------------------------------------------
# Null / missing input guards
# ---------------------------------------------------------------------------


def test_plan_update_null_sections_returns_422(tmp_path: Path):
    """POST /plan/update with sections=null returns 422."""
    sm = _make_sm(tmp_path)

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            r = c.post("/api/plan/update", json={"sections": None})

    assert r.status_code == 422


def test_plan_update_empty_body_returns_422(tmp_path: Path):
    """POST /plan/update with completely empty body returns 422."""
    sm = _make_sm(tmp_path)

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            r = c.post("/api/plan/update", json={})

    assert r.status_code == 422
