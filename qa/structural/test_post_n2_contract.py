"""Post-Night-2 contract regression checks.

Covers gaps identified after Night 2 QA passed despite real integration issues:

  REG-POST-N2-01  canonical profile fixture validates against PROFILE_SCHEMA
  REG-POST-N2-02  agent deviation fixture (total_rows/total_columns) FAILS
                  PROFILE_SCHEMA — documents the known agent deviation and
                  ensures the schema is strict enough to catch it
  REG-POST-N2-03  GET /state with a deviating profile still returns shape
                  fields accessible to the frontend (rows ?? total_rows)
  REG-POST-N2-04  section-revise-input and section-revise-btn testids are
                  present in SectionPane; build-bottom-bar is absent (the
                  global bottom bar was removed post-Night-2)
  REG-POST-N2-05  e2e Playwright specs all live under frontend/tests/e2e/
                  (not a stray top-level e2e/ dir) so they are picked up by
                  the configured testDir

Root causes each check guards against:
- REG-POST-N2-01/02: agent output accepted and stored without jsonschema
  validation; field name deviation (total_rows vs rows) was invisible to QA
- REG-POST-N2-03: frontend rendered undefined because it read shape.rows
  which was absent in the deviation variant; no end-to-end data-flow test
- REG-POST-N2-04: stale testid in section-build.spec.ts was never caught
  because the spec lived outside Playwright's testDir
- REG-POST-N2-05: same root cause as REG-POST-N2-04
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import jsonschema
import pytest
from fastapi.testclient import TestClient

from backend.agent.prompts.profile import PROFILE_SCHEMA
from backend.core.state_manager import StateManager
from backend.main import app

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent.parent / "fixtures"
FRONTEND_SRC = Path(__file__).parent.parent.parent / "frontend" / "src"
FRONTEND_E2E = Path(__file__).parent.parent.parent / "frontend" / "tests" / "e2e"


# ---------------------------------------------------------------------------
# REG-POST-N2-01  canonical fixture validates against PROFILE_SCHEMA
# ---------------------------------------------------------------------------


def test_canonical_profile_passes_schema():
    """profile_canonical.json must validate against PROFILE_SCHEMA."""
    profile = json.loads((FIXTURES / "profile_canonical.json").read_text())
    jsonschema.validate(instance=profile, schema=PROFILE_SCHEMA)


# ---------------------------------------------------------------------------
# REG-POST-N2-02  deviation fixture FAILS PROFILE_SCHEMA
# Confirms the schema is strict enough to catch total_rows/total_columns.
# ---------------------------------------------------------------------------


def test_agent_deviation_fails_schema():
    """profile_agent_deviation.json must NOT validate against PROFILE_SCHEMA.

    The agent wrote total_rows/total_columns instead of rows/columns.
    PROFILE_SCHEMA requires rows and columns; this test asserts the schema
    rejects the deviation so any future recurrence is caught at the gate.
    """
    profile = json.loads((FIXTURES / "profile_agent_deviation.json").read_text())
    # Strip the _note key before validating (it's documentation, not agent output)
    profile.pop("_note", None)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=profile, schema=PROFILE_SCHEMA)


# ---------------------------------------------------------------------------
# REG-POST-N2-03  GET /state with deviation profile exposes shape to frontend
# The frontend reads shape.rows ?? shape.total_rows; both paths must be
# reachable when the stored profile has either variant.
# ---------------------------------------------------------------------------


@pytest.fixture()
def client_with_profile(tmp_path):
    state_path = tmp_path / "state.json"
    with patch("backend.main.StateManager", lambda: StateManager(path=state_path)):
        with TestClient(app) as c:
            yield c, StateManager(path=state_path)


def _shape_rows(profile: dict) -> int | None:
    shape = profile.get("shape", {})
    return shape.get("rows") or shape.get("total_rows")


def _shape_columns(profile: dict) -> int | None:
    shape = profile.get("shape", {})
    return shape.get("columns") or shape.get("total_columns")


@pytest.mark.parametrize(
    "fixture_name",
    [
        "profile_canonical.json",
        "profile_agent_deviation.json",
    ],
)
def test_get_state_shape_accessible_for_both_variants(fixture_name, tmp_path):
    """GET /state must return a profile where the frontend can read shape values.

    Tests both the canonical (rows/columns) and deviation (total_rows/total_columns)
    variants. The frontend reads shape.rows ?? shape.total_rows; this test asserts
    at least one of those paths is populated in the stored profile.
    """
    fixture = json.loads((FIXTURES / fixture_name).read_text())
    fixture.pop("_note", None)

    state_path = tmp_path / "state.json"
    sm = StateManager(path=state_path)
    sm.update(stage="profiling", profile=fixture)

    with patch("backend.main.StateManager", lambda: StateManager(path=state_path)):
        with TestClient(app) as client:
            resp = client.get("/state")
    assert resp.status_code == 200
    profile = resp.json().get("profile", {})
    assert profile, "profile must be present in GET /state response"
    assert _shape_rows(profile) is not None, (
        f"shape rows field missing in {fixture_name}: shape={profile.get('shape')}"
    )
    assert _shape_columns(profile) is not None, (
        f"shape columns field missing in {fixture_name}: shape={profile.get('shape')}"
    )


# ---------------------------------------------------------------------------
# REG-POST-N2-04  per-section revision testids present; global bottom bar absent
# ---------------------------------------------------------------------------


def test_section_revise_testids_present_global_bottom_bar_absent():
    """SectionPane must have section-revise-input and section-revise-btn.

    build-bottom-bar must be absent — it was removed post-Night-2 when each
    section got its own revision controls. Guards against re-introduction.
    """
    pane = (FRONTEND_SRC / "components" / "SectionPane.tsx").read_text()
    assert "section-revise-input" in pane, (
        "section-revise-input testid missing from SectionPane"
    )
    assert "section-revise-btn" in pane, (
        "section-revise-btn testid missing from SectionPane"
    )
    assert "build-bottom-bar" not in pane, (
        "build-bottom-bar testid found in SectionPane — global bottom bar was removed post-Night-2"
    )


# ---------------------------------------------------------------------------
# REG-POST-N2-05  all Playwright e2e specs live under frontend/tests/e2e/
# ---------------------------------------------------------------------------


def test_no_stray_e2e_specs_outside_testdir():
    """No *.spec.ts files may live outside frontend/tests/e2e/.

    Playwright's testDir is configured as ./tests, so any spec outside that
    directory is silently never run. This test ensures the e2e/ layout stays
    correct.
    """
    frontend_root = FRONTEND_E2E.parent.parent  # frontend/
    stray = [
        p
        for p in frontend_root.rglob("*.spec.ts")
        if not str(p).startswith(str(FRONTEND_E2E)) and "node_modules" not in str(p)
    ]
    assert not stray, (
        f"Spec files found outside frontend/tests/e2e/ (they will never run): {stray}"
    )
