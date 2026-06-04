"""Unit tests for POST /section/:id/accept.

TDD: tests written before the implementation.

Acceptance criteria covered:
- POST /section/:id/accept → section marked accepted, returns 204.
- No OpenCode call made.
- Unknown ID → 400 section_not_found error envelope.
- Section not in proposed status → 400 section_not_proposed error envelope.

Architecture constraint:
- Zero OpenCode calls (verified via mock).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
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

_PLAN_WITH_ACCEPTED = [
    {
        "id": "sec_01",
        "title": "Cohort overview",
        "hypothesis": "Establish churn rate",
        "status": "accepted",
    },
    {
        "id": "sec_02",
        "title": "Churn by tier",
        "hypothesis": "Tier drives churn",
        "status": "proposed",
    },
]


def _make_client(tmp_path: Path, plan: list | None = None) -> TestClient:
    """Return a TestClient with a fresh StateManager seeded with the given plan."""
    state_path = tmp_path / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(stage="building", plan=plan if plan is not None else list(_PLAN_WITH_PROPOSED))

    with patch("backend.main.StateManager", lambda: sm):
        client = TestClient(app)
        return client


@pytest.fixture()
def client(tmp_path: Path):
    """TestClient with two proposed sections."""
    state_path = tmp_path / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(stage="building", plan=list(_PLAN_WITH_PROPOSED))

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            yield c


# ---------------------------------------------------------------------------
# Happy path — 204 + status updated
# ---------------------------------------------------------------------------


def test_section_accept_returns_204(tmp_path):
    """POST /section/sec_01/accept returns 204 No Content."""
    state_path = tmp_path / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(stage="building", plan=list(_PLAN_WITH_PROPOSED))

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            r = c.post("/api/section/sec_01/accept")

    assert r.status_code == 204


def test_section_accept_updates_status_in_state(tmp_path):
    """POST /section/sec_01/accept sets the section status to 'accepted'."""
    state_path = tmp_path / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(stage="building", plan=list(_PLAN_WITH_PROPOSED))

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            c.post("/api/section/sec_01/accept")

    plan = sm.get_state()["plan"]
    sec_01 = next(s for s in plan if s["id"] == "sec_01")
    assert sec_01["status"] == "accepted", f"Expected 'accepted', got {sec_01['status']!r}"


def test_section_accept_only_mutates_target_section(tmp_path):
    """POST /section/sec_01/accept leaves other sections unchanged."""
    state_path = tmp_path / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(stage="building", plan=list(_PLAN_WITH_PROPOSED))

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            c.post("/api/section/sec_01/accept")

    plan = sm.get_state()["plan"]
    sec_02 = next(s for s in plan if s["id"] == "sec_02")
    assert sec_02["status"] == "proposed", (
        f"sec_02 should remain 'proposed', got {sec_02['status']!r}"
    )


def test_section_accept_second_section(tmp_path):
    """POST /section/sec_02/accept marks the second section accepted."""
    state_path = tmp_path / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(stage="building", plan=list(_PLAN_WITH_PROPOSED))

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            r = c.post("/api/section/sec_02/accept")

    assert r.status_code == 204
    plan = sm.get_state()["plan"]
    sec_02 = next(s for s in plan if s["id"] == "sec_02")
    assert sec_02["status"] == "accepted"


# ---------------------------------------------------------------------------
# Error path — unknown section ID
# ---------------------------------------------------------------------------


def test_section_accept_unknown_id_returns_400(tmp_path):
    """POST /section/sec_99/accept returns 400 with section_not_found."""
    state_path = tmp_path / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(stage="building", plan=list(_PLAN_WITH_PROPOSED))

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            r = c.post("/api/section/sec_99/accept")

    assert r.status_code == 400
    body = r.json()
    assert body.get("error") == "section_not_found"
    assert "sec_99" in body.get("message", "")


def test_section_accept_unknown_id_error_envelope_shape(tmp_path):
    """Error envelope must have 'error' and 'message' keys (contract §4)."""
    state_path = tmp_path / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(stage="building", plan=list(_PLAN_WITH_PROPOSED))

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            r = c.post("/api/section/sec_99/accept")

    body = r.json()
    assert "error" in body
    assert "message" in body


# ---------------------------------------------------------------------------
# Error path — section not in proposed status
# ---------------------------------------------------------------------------


def test_section_accept_already_accepted_returns_400(tmp_path):
    """POST /section/sec_01/accept on an already-accepted section returns 400."""
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
            r = c.post("/api/section/sec_01/accept")

    assert r.status_code == 400
    body = r.json()
    assert body.get("error") == "section_not_proposed"


def test_section_accept_dropped_section_returns_400(tmp_path):
    """POST /section/sec_01/accept on a dropped section returns 400."""
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
            r = c.post("/api/section/sec_01/accept")

    assert r.status_code == 400
    body = r.json()
    assert body.get("error") == "section_not_proposed"


# ---------------------------------------------------------------------------
# Edge case — empty plan
# ---------------------------------------------------------------------------


def test_section_accept_empty_plan_returns_400(tmp_path):
    """POST /section/sec_01/accept with an empty plan returns 400 section_not_found."""
    state_path = tmp_path / "state.json"
    sm = StateManager(path=state_path)
    sm.load()
    sm.update(stage="building", plan=[])

    with patch("backend.main.StateManager", lambda: sm):
        with TestClient(app) as c:
            c.app.state.state_manager = sm
            r = c.post("/api/section/sec_01/accept")

    assert r.status_code == 400
    body = r.json()
    assert body.get("error") == "section_not_found"


# ---------------------------------------------------------------------------
# Zero OpenCode calls
# ---------------------------------------------------------------------------


def test_section_accept_makes_zero_opencode_calls(tmp_path):
    """POST /section/sec_01/accept must make zero calls to the OpenCode client."""
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
            c.post("/api/section/sec_01/accept")

    mock_client.prompt.assert_not_awaited()
